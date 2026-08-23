from meal_organizer.db import Database


def test_inventory_roundtrip(tmp_path):
    db = Database(tmp_path / "test.db")
    db.upsert_inventory("rice", 500, "g", "cupboard")
    db.upsert_inventory("eggs", 6, "unit", "fridge")

    items = db.list_inventory()
    assert [item.name for item in items] == ["eggs", "rice"]
    assert items[1].quantity == 500

    assert db.remove_inventory("eggs") is True
    assert db.remove_inventory("missing") is False
