"""The income editor submits only changed fields."""
import pytest


@pytest.mark.anyio
async def test_partial_income_edits_preserve_independently_saved_fields(client):
    plan = await client.post('/api/plans', json={'name': 'Income audit', 'birth_year': 1990})
    assert plan.status_code == 201
    pid = plan.json()['id']
    created = await client.post(f'/api/plans/{pid}/incomes', json={
        'name': 'Consulting', 'annual_amount': 12000, 'growth_rate': 0,
        'is_self_employed': True, 'withholding_percent': 15,
    })
    assert created.status_code == 201
    url = f"/api/plans/{pid}/incomes/{created.json()['id']}"
    # Both forms opened the original record. A edits name, B edits amount.
    assert (await client.put(url, json={'name': 'Renamed consulting'})).status_code == 200
    amount = await client.put(url, json={'annual_amount': 24000})
    assert amount.status_code == 200
    assert amount.json()['name'] == 'Renamed consulting'
    # Clearing an optional field must stay distinct from omitting that field.
    assert (await client.put(url, json={'withholding_percent': None})).status_code == 200
    reloaded = await client.get(f'/api/plans/{pid}/incomes')
    record = reloaded.json()[0]
    assert record['name'] == 'Renamed consulting'
    assert record['annual_amount'] == 24000
    assert record['withholding_percent'] is None
    assert record['is_self_employed'] is True
    assert record['growth_rate'] == 0


@pytest.mark.anyio
async def test_rejected_income_name_has_field_detail_and_preserves_saved_record(client):
    plan = await client.post('/api/plans', json={'name': 'UX synthetic household', 'birth_year': 1990})
    pid = plan.json()['id']
    created = await client.post(f'/api/plans/{pid}/incomes', json={'name': 'Salary', 'annual_amount': 100000})
    url = f"/api/plans/{pid}/incomes/{created.json()['id']}"
    for _ in range(2):
        rejected = await client.put(url, json={'name': 'UX income ' + 'A' * 250})
        assert rejected.status_code == 422
        assert rejected.json()['error']['details'] == [
            {'field': 'name', 'reason': 'String should have at most 255 characters'}
        ]
    saved = (await client.get(f'/api/plans/{pid}/incomes')).json()[0]
    assert saved['name'] == 'Salary'
    assert saved['annual_amount'] == 100000
    assert (await client.put(url, json={'name': 'Corrected salary'})).status_code == 200
    saved = (await client.get(f'/api/plans/{pid}/incomes')).json()[0]
    assert saved['name'] == 'Corrected salary'
    assert saved['annual_amount'] == 100000
