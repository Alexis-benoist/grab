from contextlib import suppress
from datetime import datetime
from queue import Empty, PriorityQueue

from grab.spider.queue_backend.base import QueueInterface


class QueueBackend(QueueInterface):
    def __init__(self, spider_name, **kwargs):
        super().__init__(spider_name, **kwargs)
        self.queue_object = PriorityQueue()
        self.schedule_list = []

    def put(self, task, priority, schedule_time=None):
        if schedule_time is None:
            self.queue_object.put((priority, task))
        else:
            self.schedule_list.append((schedule_time, task))

    def get(self):
        now = datetime.utcnow()

        removed_indexes = []
        index = 0  # noqa: SIM113
        for schedule_time, task in self.schedule_list:
            if schedule_time <= now:
                self.put(task, 1)
                removed_indexes.append(index)
            index += 1

        self.schedule_list = [
            x for idx, x in enumerate(self.schedule_list) if idx not in removed_indexes
        ]

        _, task = self.queue_object.get(block=False)
        return task

    def size(self):
        return self.queue_object.qsize() + len(self.schedule_list)

    def clear(self):
        with suppress(Empty):
            while True:
                self.queue_object.get(False)
        self.schedule_list = []

    def close(self):
        pass
