
import sys
import time
import socket
import select

from .XMODEM import XMODEM
import logging


TCP_PORT = 2222
UDP_PORT = 3333
BUFFER_SIZE = 1024
SOCKET_TIMEOUT = 0.3  # s

# ==============================================================================
# Machine Detector class
# ==============================================================================
class MachineDetector:
    def __init__(self):
        pass

    def get_machine_list(self):
        UDP_IP = "0.0.0.0"
        machine_list = []
        machine_name_list = []
        # test
        # machine_list.append({'machine': 'Dummy machine', 'ip': '127.0.0.1', 'port': 7777, 'busy': False})
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1)
            sock.bind((UDP_IP, UDP_PORT))
            t = tr = time.time()
            while t - tr < 3:
                fields = []
                try:
                    data, addr = sock.recvfrom(128)  # buffer size is 1024 bytes
                    fields = data.decode('utf-8').split(',')
                except:
                    pass
                if len(fields) > 3 and fields[0] not in machine_name_list:
                    machine_name_list.append(fields[0])
                    machine_list.append({'machine': fields[0], 'ip': fields[1], 'port': int(fields[2]), 'busy': True if fields[3] == '1' else False})
                    print(machine_list[-1])
                    #break
                t = time.time()
            sock.close()
        except:
            print(sys.exc_info()[1])
        return machine_list



# ==============================================================================
# WiFi stream class
# ==============================================================================
class WIFIStream:

    socket = None
    modem = None

    # ----------------------------------------------------------------------
    def __init__(self):

        self.modem = XMODEM(self.getc, self.putc, 'xmodem8k')

        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.WARNING)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.modem.log.addHandler(handler)

    # ----------------------------------------------------------------------
    def send(self, data):
        self.socket.send(data)

    # ----------------------------------------------------------------------
    def recv(self):
        return self.socket.recv(BUFFER_SIZE)

    # ----------------------------------------------------------------------
    def open(self, address):
        self.socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
        ip_port = address.split(':')
        self.socket.settimeout(2)
        self.socket.connect((address.split(':')[0], (int)(address.split(':')[1]) if len(ip_port) > 1 else TCP_PORT))
        self.socket.settimeout(SOCKET_TIMEOUT)

        return True

    # ----------------------------------------------------------------------
    def close(self):
        if self.socket is None: return
        try:
            self.modem.clear_mode_set()
            self.socket.close()
        except:
            pass
        self.socket = None
        return True

    # ----------------------------------------------------------------------
    def waiting_for_send(self):
        socket_list = [self.socket]
        # Get the list sockets which are readable
        read_sockets, write_sockets, error_sockets = select.select([], socket_list, [], 0)
        for sock in write_sockets:
            # incoming message from remote server
            if sock == self.socket:
                return True
        return False


    # ----------------------------------------------------------------------
    def waiting_for_recv(self):
        socket_list = [self.socket]
        # Get the list sockets which are readable
        read_sockets, write_sockets, error_sockets = select.select(socket_list, [], [], 0)
        for sock in read_sockets:
            # incoming message from remote server
            if sock == self.socket:
                return True
        return False

    # ----------------------------------------------------------------------
    def getc(self, size, timeout = 0.5):
        t1 = time.time()
        data = bytearray()
        while len(data) < size and time.time() - t1 <= timeout:
            if self.waiting_for_recv():
                try:
                    data.extend(self.socket.recv(size - len(data)))
                except:
                    print(sys.exc_info()[1])
            else:
                time.sleep(0.0001)

        if len(data) == size:
            return data

        return None

    def putc(self, data, timeout = 0.5):
        return self.socket.send(data) or None

    def upload(self, filename, local_md5, callback):
        # do upload
        stream = open(filename, 'rb')
        result = self.modem.send(stream, md5 = local_md5, retry = 10, callback = callback)
        stream.close()
        return result

    def download(self, filename, local_md5, callback):
        stream = open(filename, 'wb')
        result = self.modem.recv(stream, md5 = local_md5, retry = 10, callback = callback)
        stream.close()
        return result

    def cancel_process(self):
        self.modem.canceled = True