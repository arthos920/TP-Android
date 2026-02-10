transport = await self._stack.enter_async_context(
    streamable_http_client(self.url, headers=self.headers)
)


transport = await self._stack.enter_async_context(
    streamable_http_client(self.url)
)

class MCPRemoteHTTP:
    def __init__(self, url: str):
        self.url = url
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPRemoteHTTP":
        transport = await self._stack.enter_async_context(
            streamable_http_client(self.url)
        )
        read_stream, write_stream = transport

        self.session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._stack.aclose()

    async def list_tools(self):
        resp = await self.session.list_tools()
        return resp.tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
        return await self.session.call_tool(name, args)