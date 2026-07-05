import asyncio


def test_mcp_tools_registered():
    import mcp_server

    tools = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    for expected in (
        "where_is",
        "search_inventory",
        "get_item",
        "get_bin_contents",
        "get_location_contents",
        "list_checkouts",
        "check_out_item",
        "check_in_item",
        "update_item",
        "move_item",
        "set_checkout_details",
        "inventory_statistics",
    ):
        assert expected in tools
    # Adding and deleting items are intentionally NOT exposed to Home Assistant.
    assert "create_item" not in tools
    assert "delete_item" not in tools
