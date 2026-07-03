import asyncio


def test_mcp_tools_registered():
    import mcp_server

    tools = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    for expected in (
        "where_is",
        "search_inventory",
        "get_item",
        "list_checkouts",
        "check_out_item",
        "check_in_item",
        "create_item",
        "inventory_statistics",
    ):
        assert expected in tools
