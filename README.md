class MCPRemoteHTTP:
    def __init__(self, url: str):
        self.url = url
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPRemoteHTTP":
        transport = await self._stack.enter_async_context(streamable_http_client(self.url))

        # ---- Robust unpacking across mcp versions ----
        if isinstance(transport, tuple) or isinstance(transport, list):
            if len(transport) < 2:
                raise TypeError(f"streamable_http_client returned tuple/list with len < 2: {len(transport)}")
            read_stream, write_stream = transport[0], transport[1]

        elif hasattr(transport, "read_stream") and hasattr(transport, "write_stream"):
            read_stream, write_stream = transport.read_stream, transport.write_stream

        elif hasattr(transport, "streams"):
            streams = transport.streams
            if not isinstance(streams, (tuple, list)) or len(streams) < 2:
                raise TypeError("streamable_http_client returned object with .streams but <2 streams")
            read_stream, write_stream = streams[0], streams[1]

        else:
            raise TypeError(f"Unknown transport from streamable_http_client: {type(transport)}")

        self.session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._stack.aclose()

    async def list_tools(self):
        assert self.session
        return (await self.session.list_tools()).tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
        assert self.session
        return await self.session.call_tool(name, args)