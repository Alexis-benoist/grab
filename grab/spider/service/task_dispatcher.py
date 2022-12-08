from queue import Empty, Queue

from grab.error import ResponseNotValid
from grab.spider.error import FatalError, SpiderError
from grab.spider.task import Task

from .base import BaseService


class TaskDispatcherService(BaseService):
    def __init__(self, spider):
        super().__init__(spider)
        self.input_queue = Queue()
        self.worker = self.create_worker(self.worker_callback)
        self.register_workers(self.worker)

    def start(self):
        self.worker.start()

    def worker_callback(self, worker):
        while not worker.stop_event.is_set():
            worker.process_pause_signal()
            try:
                result, task, meta = self.input_queue.get(True, 0.1)
            except Empty:
                pass
            else:
                self.process_service_result(result, task, meta)

    def process_service_result(self, result, task, meta=None):
        """
        Process result submitted from any service to task dispatcher service.

        Result could be:
        * Task
        * None
        * Task instance
        * ResponseNotValid-based exception
        * Arbitrary exception
        * Network response:
            {ok, ecode, emsg, error_abbr, exc, grab, grab_config_backup}

        Exception can come only from parser_service and it always has
        meta {"from": "parser", "exc_info": <...>}
        """
        if meta is None:
            meta = {}
        if isinstance(result, Task):
            self.spider.add_task(result)
        elif result is None:
            pass
        elif isinstance(result, ResponseNotValid):
            self.spider.add_task(task.clone())
            error_code = result.__class__.__name__.replace("_", "-")
            self.spider.stat.inc("integrity:%s" % error_code)
        elif isinstance(result, Exception):
            if task:
                handler = self.spider.find_task_handler(task)
                handler_name = getattr(handler, "__name__", "NONE")
            else:
                handler_name = "NA"
            self.spider.process_parser_error(
                handler_name,
                task,
                meta["exc_info"],
            )
            if isinstance(result, FatalError):
                self.spider.fatal_error_queue.put(meta["exc_info"])
        elif isinstance(result, dict) and "grab" in result:
            self.process_network_result(result, task)
        else:
            raise SpiderError("Unknown result received from a service: %s" % result)

    def process_network_result(self, result, task):
        # TODO: Move to network service
        # starts
        self.spider.log_network_result_stats(result, task)
        # ends
        is_valid = False
        if task.get("raw"):
            is_valid = True
        elif result["ok"]:
            res_code = result["grab"].doc.code
            is_valid = self.spider.is_valid_network_response_code(res_code, task)
        if is_valid:
            self.spider.parser_service.input_queue.put((result, task))
        else:
            self.spider.log_failed_network_result(result)
            # Try to do network request one more time
            # TODO:
            # Implement valid_try_limit
            # Use it if request failed not because of network error
            # But because of content integrity check
            if self.spider.network_try_limit > 0:
                task.setup_grab_config(result["grab_config_backup"])
                self.spider.add_task(task)
        self.spider.stat.inc("spider:request")
