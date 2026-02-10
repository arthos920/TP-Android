async def main():
    try:
        await duo_jira_to_mobile_async_streaming(...)
    except Exception as e:
        print("\n❌ ERREUR:", repr(e))