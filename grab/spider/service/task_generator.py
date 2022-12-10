from __future__ import annotations

import time
from typing import Iterator

from ..interface import BaseSpider
from ..task import Task
from .base import BaseService


class TaskGeneratorService(BaseService):
    def __init__(self, spider: BaseSpider, real_generator: Iterator[Task]) -> None:
        super().__init__(spider)
        self.real_generator = real_generator
        self.task_queue_threshold = max(200, self.spider.thread_number * 2)
        self.worker = self.create_worker(self.worker_callback)
        self.register_workers(self.worker)

    def worker_callback(self, worker):
        while not worker.stop_event.is_set():
            worker.process_pause_signal()
            queue_size = max(
                self.spider.task_queue.size(),
                self.spider.parser_service.input_queue.qsize(),
            )
            if queue_size < self.task_queue_threshold:
                try:
                    for _ in range(self.task_queue_threshold - queue_size):
                        if worker.pause_event.is_set():
                            return
                        task = next(self.real_generator)
                        self.spider.task_dispatcher.input_queue.put(
                            (task, None, {"source": "task_generator"})
                        )
                except StopIteration:
                    return
            else:
                time.sleep(0.1)
