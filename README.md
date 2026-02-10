transport = await self._stack.enter_async_context(streamable_http_client(self.url))

# Cas 1: tuple (len >= 2) -> on prend les 2 premiers
if isinstance(transport, tuple) and len(transport) >= 2:
    read_stream, write_stream = transport[0], transport[1]

# Cas 2: attributs
elif hasattr(transport, "read_stream") and hasattr(transport, "write_stream"):
    read_stream = transport.read_stream
    write_stream = transport.write_stream

# Cas 3: attribut streams
elif hasattr(transport, "streams"):
    streams = transport.streams
    read_stream, write_stream = streams[0], streams[1]

else:
    raise TypeError(f"Transport streamable_http_client inconnu: {type(transport)}")