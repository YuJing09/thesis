#!/usr/bin/env python
"""
Note:
Part of this code was copied and modified from github.com/mila-udem/fuel.git (MIT License)
"""
import logging
import os
import numpy
import zmq
from numpy.lib.format import header_data_from_array_1_0
import random
#from datag import camerapath,label,vpath,vcamerapath
import six
from server_path import path
if six.PY3:
  buffer_ = memoryview
else:
  buffer_ = buffer  # noqa

logger = logging.getLogger(__name__)


def send_arrays(socket, arrays, stop=False):
  """Send NumPy arrays using the buffer interface and some metadata.

  Parameters
  ----------
  socket : :class:`zmq.Socket`
  The socket to send data over.
  arrays : list
  A list of :class:`numpy.ndarray` to transfer.
  stop : bool, optional
  Instead of sending a series of NumPy arrays, send a JSON object
  with a single `stop` key. The :func:`recv_arrays` will raise
  ``StopIteration`` when it receives this.

  Notes
  -----
  The protocol is very simple: A single JSON object describing the array
  format (using the same specification as ``.npy`` files) is sent first.
  Subsequently the arrays are sent as bytestreams (through NumPy's
  support of the buffering protocol).

  """
  if arrays:
    # The buffer protocol only works on contiguous arrays
    arrays = [numpy.ascontiguousarray(array) for array in arrays]
  if stop:
    headers = {'stop': True}
    socket.send_json(headers)
  else:
    headers = [header_data_from_array_1_0(array) for array in arrays]
    socket.send_json(headers, zmq.SNDMORE)
    for array in arrays[:-1]:
      socket.send(array, zmq.SNDMORE)
    socket.send(arrays[-1])


def recv_arrays(socket):
  """Receive a list of NumPy arrays.

  Parameters
  ----------
  socket : :class:`zmq.Socket`
  The socket to receive the arrays on.

  Returns
  -------
  list
  A list of :class:`numpy.ndarray` objects.

  Raises
  ------
  StopIteration
  If the first JSON object received contains the key `stop`,
  signifying that the server has finished a single epoch.

  """
  headers = socket.recv_json()
  if 'stop' in headers:
    raise StopIteration
  arrays = []
  for header in headers:
    data = socket.recv()
    buf = buffer_(data)
    array = numpy.frombuffer(buf, dtype=numpy.dtype(header['descr']))
    array.shape = header['shape']
    if header['fortran_order']:
      array.shape = header['shape'][::-1]
      array = array.transpose()
    arrays.append(array)
  return arrays


def client_generator(port=5557, host="localhost", hwm=20):
  """Generator in client side should extend this generator

  Parameters
  ----------

  port : int
  hwm : int, optional
  The `ZeroMQ high-water mark (HWM)
  <http://zguide.zeromq.org/page:all#High-Water-Marks>`_ on the
  sending socket. Increasing this increases the buffer, which can be
  useful if your data preprocessing times are very random.  However,
  it will increase memory usage. There is no easy way to tell how
  many batches will actually be queued with a particular HWM.
  Defaults to 10. Be sure to set the corresponding HWM on the
  receiving end as well.
  """
  context = zmq.Context()
  socket = context.socket(zmq.PULL)
  socket.set_hwm(hwm)
  socket.connect("tcp://{}:{}".format(host, port))
  logger.info('client started')
  while True:
    data = recv_arrays(socket)
    yield tuple(data)


def start_server(data_stream, port=5557, hwm=20):
  """Start a data processing server.

  This command starts a server in the current process that performs the
  actual data processing (by retrieving data from the given data stream).
  It also starts a second process, the broker, which mediates between the
  server and the client. The broker also keeps a buffer of batches in
  memory.

  Parameters
  ----------
  data_stream : generator
  The data stream to return examples from.
  port : int, optional
  The port the server and the client (training loop) will use to
  communicate. Defaults to 5557.
  hwm : int, optional
  The `ZeroMQ high-water mark (HWM)
  <http://zguide.zeromq.org/page:all#High-Water-Marks>`_ on the
  sending socket. Increasing this increases the buffer, which can be
  useful if your data preprocessing times are very random.  However,
  it will increase memory usage. There is no easy way to tell how
  many batches will actually be queued with a particular HWM.
  Defaults to 10. Be sure to set the corresponding HWM on the
  receiving end as well.
  """
  logging.basicConfig(level='INFO')

  context = zmq.Context()
  socket = context.socket(zmq.PUSH)
  socket.set_hwm(hwm)
  socket.bind('tcp://*:{}'.format(port))

  # it = itertools.tee(data_stream)
  it = data_stream

  logger.info('server started')
  while True:
    try:
      data = next(it)
      stop = False
      logger.debug("sending {} arrays".format(len(data)))
    except StopIteration:
      it = data_stream
      data = None
      stop = True
      logger.debug("sending StopIteration")
    
    send_arrays(socket, data, stop=stop)

# Example
if __name__ == "__main__":
  from datagen_steering import datagen
  import argparse
  import random
  # Parameters
  parser = argparse.ArgumentParser(description='MiniBatch server')
  parser.add_argument('--batch', dest='batch', type=int, default=32, help='Batch size')
  parser.add_argument('--time', dest='time', type=int, default=10, help='Number of frames per sample')
  parser.add_argument('--port', dest='port', type=int, default=5557, help='Port of the ZMQ server')
  parser.add_argument('--buffer', dest='buffer', type=int, default=20, help='High-water mark. Increasing this increses buffer and memory usage.')
  parser.add_argument('--prep', dest='prep', action='store_true', default=False, help='Use images preprocessed by vision model.')
  parser.add_argument('--leads', dest='leads', action='store_true', default=False, help='Use x, y and speed radar lead info.')
  parser.add_argument('--nogood', dest='nogood', action='store_true', default=False, help='Ignore `goods` filters.')
  parser.add_argument('--validation', dest='validation', action='store_true', default=False, help='Serve validation dataset instead.')
  args, more = parser.parse_known_args()
  #print(path)
  
  
  
  train_len=int(0.5*len(path))
  val_len=int(0.25*len(path))

  train_path=path[:train_len]
 

  #  for validation
  validation_path =path[train_len:train_len+val_len]
  if args.validation:
    datapath = validation_path
  else:
    datapath = train_path
  
  gen = datagen(datapath, max_time_len=args.time, batch_size=args.batch)
  
  start_server(gen, port=args.port, hwm=args.buffer)
  
