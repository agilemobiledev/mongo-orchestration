#!/usr/bin/python
# coding=utf-8

import logging
logger = logging.getLogger(__name__)
import process
from uuid import uuid4
from singleton import Singleton
from container import Container
import pymongo
import os
import tempfile
import stat


class Host(object):
    """Class Host represents behaviour of  mongo instances """

    # default params for all mongo instances
    mongod_default = {"noprealloc": True, "nojournal": True, "smallfiles": True, "oplogSize": 10}

    def __init_db(self, dbpath):
        if not dbpath:
            dbpath = tempfile.mkdtemp(prefix="mongo-")
        if not os.path.exists(dbpath):
            os.makedirs(dbpath)
        return dbpath

    def __init_auth_key(self, auth_key, folder):
        key_file = os.path.join(os.path.join(folder, 'key'))
        open(key_file, 'w').write(auth_key)
        os.chmod(key_file, stat.S_IRUSR)
        return key_file

    def __init_logpath(self, log_path):
        if log_path and not os.path.exists(os.path.dirname(log_path)):
            os.makedirs(log_path)

    def __init_mongod(self, params):
        cfg = self.mongod_default.copy()
        cfg.update(params)

        # create db folder
        cfg['dbpath'] = self.__init_db(cfg.get('dbpath', None))

        # use keyFile
        if self.auth_key:
            cfg['auth'] = True
            cfg['keyFile'] = self.__init_auth_key(self.auth_key, cfg['dbpath'])

        if self.login:
            cfg['auth'] = True

        # create logpath
        self.__init_logpath(cfg.get('logpath', None))

        # find open port
        if 'port' not in cfg:
            cfg['port'] = process.PortPool().port(check=True)

        return process.write_config(cfg), cfg

    def __init_mongos(self, params):
        cfg = params.copy()

        self.__init_logpath(cfg.get('logpath', None))

        # use keyFile
        if self.auth_key:
            cfg['keyFile'] = self.__init_auth_key(self.auth_key, tempfile.mkdtemp())

        if 'port' not in cfg:
            cfg['port'] = process.PortPool().port(check=True)

        return process.write_config(cfg), cfg

    def __init__(self, name, params, auth_key=None, login='', password=''):
        """Args:
            name - name of process (mongod or mongos)
            params - dictionary with params for mongo process
            auth_key - authorization key
            login - username for the  admin collection
            password - password
        """
        self.name = name  # name of process
        self.login = login
        self.password = password
        self.auth_key = auth_key
        self.admin_added = False
        self.pid = None  # process pid
        self.host = None  # hostname without port
        self.hostname = None  # string like host:port
        self.is_mongos = False

        proc_name = os.path.split(name)[1].lower()
        if proc_name.startswith('mongod'):
            self.config_path, self.cfg = self.__init_mongod(params)

        elif proc_name.startswith('mongos'):
            self.is_mongos = True
            self.config_path, self.cfg = self.__init_mongos(params)

        else:
            self.config_path, self.cfg = None, {}

        self.port = self.cfg.get('port', None)  # connection port

    @property
    def connection(self):
        """return authenticated connection"""
        c = pymongo.Connection(self.hostname)
        if not self.is_mongos and (self.login and self.password):
            c.admin.authenticate(self.login, self.password)
        return c

    def run_command(self, command, arg=None, is_eval=False):
        """run command on the host

        Args:
            command - command string
            arg - command argument
            is_eval - if True execute command as eval

        return command's result
        """
        mode = is_eval and 'eval' or 'command'

        if isinstance(arg, tuple):
            name, d = arg
        else:
            name, d = arg, {}

        result = getattr(self.connection.admin, mode)(command, name, **d)
        return result

    @property
    def is_alive(self):
        return process.proc_alive(self.pid)

    def info(self):
        """return info about host as dict object"""
        proc_info = {"name": self.name, "params": self.cfg, "alive": self.is_alive,
                     "pid": self.pid, "optfile": self.config_path}

        server_info = {}
        status_info = {}
        if self.hostname and self.cfg.get('port', None):
            try:
                c = pymongo.Connection(self.hostname.split(':')[0], self.cfg['port'])
                server_info = c.server_info()
                status_info = {"primary": c.is_primary, "mongos": c.is_mongos, "locked": c.is_locked}
            except (pymongo.errors.AutoReconnect, pymongo.errors.OperationFailure, pymongo.errors.ConnectionFailure):
                server_info = {}
                status_info = {}

        return {"uri": self.hostname, "statuses": status_info, "serverInfo": server_info, "procInfo": proc_info}

    def start(self, timeout=300):
        """start host
        return True of False"""
        try:
            self.pid, self.hostname = process.mprocess(self.name, self.config_path, self.cfg.get('port', None), timeout)
            self.host = self.hostname.split(':')[0]
            self.port = int(self.hostname.split(':')[1])
        except OSError:
            return False
        if not self.admin_added and self.login:
            self._add_auth()
            self.admin_added = True
        return True

    def stop(self):
        """stop host"""
        return process.kill_mprocess(self.pid)

    def restart(self, timeout=300):
        """restart host: stop() and start()
        return status of start command
        """
        self.stop()
        return self.start(timeout)

    def _add_auth(self):
        try:
            db = self.connection.admin
            db.add_user(self.login, self.password)
            db.logout()
        except pymongo.errors.OperationFailure:
            # user added successfuly but OperationFailure exception raises
            pass

    def cleanup(self):
        """remove host data"""
        process.cleanup_mprocess(self.config_path, self.cfg)


class Hosts(Singleton, Container):
    """ Hosts is a dict-like collection for Host objects"""
    _name = 'hosts'
    _obj_type = Host
    bin_path = ''
    pids_file = tempfile.mktemp(prefix="mongo-")

    def __getitem__(self, key):
        return self.info(key)

    def cleanup(self):
        """remove all hosts with their data"""
        if self._storage:
            for host_id in self._storage:
                self.remove(host_id)

    def create(self, name, params, auth_key=None, login=None, password=None, timeout=300, autostart=True):
        """create new host
        Args:
           name - process name or path
           params - dictionary with specific params for instance
           auth_key - authorization key
           login - username for the  admin collection
           password - password
           timeout -  specify how long, in seconds, a command can take before times out.
           autostart - (default: True), autostart instance
        Return host_id
           where host_id - id which can use to take the host from hosts collection
        """
        name = os.path.split(name)[1]
        try:
            host_id, host = str(uuid4()), Host(os.path.join(self.bin_path, name), params, auth_key, login, password)
            if autostart:
                if not host.start(timeout):
                    raise OSError
            self[host_id] = host
            return host_id
        except:
            raise

    def remove(self, host_id):
        """remove host and data stuff
        Args:
            host_id - host identity
        """
        host = self._storage.pop(host_id)
        host.stop()
        host.cleanup()

    def db_command(self, host_id, command, arg=None, is_eval=False):
        host = self._storage[host_id]
        return host.run_command(command, arg, is_eval)

    def command(self, host_id, command, *args):
        """run command
        Args:
            host_id - host identity
            command - command which apply to host
        """
        host = self._storage[host_id]
        try:
            if args:
                result = getattr(host, command)(args)
            else:
                result = getattr(host, command)()
        except AttributeError:
            raise ValueError
        self._storage[host_id] = host
        return result

    def info(self, host_id):
        """return dicionary object with info about host
        Args:
            host_id - host identity
        """
        result = self._storage[host_id].info()
        result['id'] = host_id
        return result

    def hostname(self, host_id):
        return self._storage[host_id].hostname

    def id_by_hostname(self, hostname):
        for host_id in self._storage:
            if self._storage[host_id].hostname == hostname:
                return host_id

    def is_alive(self, host_id):
        return self._storage[host_id].is_alive
