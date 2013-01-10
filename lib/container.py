#!/usr/bin/python
# coding=utf-8

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

from storage import Storage
import operator


class Container(object):
    """ Container is a dict-like collection for objects"""
    _storage = None
    _name = 'container'
    _obj_type = object

    def set_settings(self, pids_file, bin_path=None):
        """set path to storage"""
        self._storage = Storage(pids_file, self._name)
        self.pids_file = pids_file
        self.bin_path = bin_path or ''
        logger.debug("Storage({pids_file}, {bin_path}".format(**locals()))

    def __getitem__(self, key):
        return self._storage[key]

    def __setitem__(self, key, value):
        if isinstance(value, self._obj_type):
            self._storage[key] = value
        else:
            raise ValueError

    def __delitem__(self, key):
        obj = self._storage[key]
        operator.delitem(self._storage, key)
        del(obj)

    def __del__(self):
        self.cleanup()

    def __contains__(self, item):
        return item in self._storage

    def __iter__(self):
        for item in self._storage:
            yield item

    def __len__(self):
        return len(self._storage)

    def __nonzero__(self):
        return bool(len(self))

    def __bool__(self):
        # Python 3 compatibility
        return self.__nonzero__()

    def cleanup(self):
        for key in self:
            operator.delitem(self, key)

    def create(self):
        raise NotImplementedError("Please Implement this method")

    def remove(self):
        raise NotImplementedError("Please Implement this method")

    def info(self):
        raise NotImplementedError("Please Implement this method")
