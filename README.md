async def get_devices_payload_with_retries(
    mobile_mcp: MCPMobileStdio,
    attempts: int = 6,
    delay_s: float = 0.5,
) -> Any:
    """
    Appelle mobile_list_available_devices plusieurs fois.
    Stop dès qu'on peut extraire un device_id.
    """

    last_payload: Any = None

    for i in range(attempts):
        try:
            # ⚠️ IMPORTANT : args requis par ton MCP
            result = await mobile_mcp.call_tool(
                "mobile_list_available_devices",
                {"noParams": {}},
            )

            devices_text = mcp_result_to_text(result)

            print(
                f"\n[MOBILE] devices attempt {i+1}/{attempts} preview:\n"
                f"{devices_text[:800]}\n"
            )

            try:
                payload = json.loads(devices_text)
            except Exception:
                payload = devices_text

            last_payload = payload

            picked = extract_first_device_id(payload)
            if picked:
                print(f"[MOBILE] Device détecté dès attempt {i+1}: {picked}")
                return payload

        except Exception as e:
            print(
                f"[MOBILE] WARNING devices attempt "
                f"{i+1}/{attempts} failed: {repr(e)}"
            )

        await asyncio.sleep(delay_s * (i + 1))

    return last_payload