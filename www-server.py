#!/usr/bin/env python
import sys

from BaseHTTPServer import BaseHTTPRequestHandler,HTTPServer

PORT_NUMBER = 8080
MAX_LINES = 1000


class HTTPHandler(BaseHTTPRequestHandler):
  def do_GET(self):
    self.send_response(200)
    self.send_header('Content-type','text/plain')
    self.end_headers()
    self.wfile.write('Last %d log lines (most recent first)\n\n' % MAX_LINES)
    lines = open(sys.argv[1]).readlines()
    for line in reversed(lines[-MAX_LINES:]):
      self.wfile.write(line)
	  
if __name__ == "__main__":
  server = HTTPServer(('', PORT_NUMBER), HTTPHandler)
  server.serve_forever()