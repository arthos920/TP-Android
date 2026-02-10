class MCPRemoteHTTP:
    def __init__(self, url: str):
        self.url = url
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPRemoteHTTP":
        transport = await self._stack.enter_async_context(streamable_http_client(self.url))

        # --- Compat multi-versions ---
        # Cas 1: transport est déjà un tuple (read, write)
        if isinstance(transport, tuple) and len(transport) == 2:
            read_stream, write_stream = transport

        # Cas 2: transport a des attributs "read_stream"/"write_stream"
        elif hasattr(transport, "read_stream") and hasattr(transport, "write_stream"):
            read_stream = transport.read_stream
            write_stream = transport.write_stream

        # Cas 3: transport a un attribut "streams" ou similaire
        elif hasattr(transport, "streams"):
            streams = transport.streams
            read_stream, write_stream = streams  # en général 2 éléments

        else:
            raise TypeError(
                f"Format de transport streamable_http_client inconnu: {type(transport)}. "
                "Affiche-le pour adapter (print(transport))."
            )

        self.session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._stack.aclose()

    async def list_tools(self):
        resp = await self.session.list_tools()
        return resp.tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
        return await self.session.call_tool(name, args)