from app import create_app

app = create_app()
with app.app_context():
    for rule in app.url_map.iter_rules():
        if 'restock' in str(rule):
            print(f'{rule.methods} {rule}')

# Test the route matching
with app.test_client() as client:
    # First login
    resp = client.post('/api/v1/users/register', json={'email': 't@t.com', 'password': 'password', 'name': 'T'})
    print(f'Register status: {resp.status_code}')
    
    resp = client.post('/api/v1/users/login', json={'username': 't@t.com', 'password': 'password'})
    print(f'Login status: {resp.status_code}')
    token = resp.get_json()['token']
    print(f'Token: {token}')
    
    # Set the token
    client.environ_base['HTTP_AUTHORIZATION'] = token
    
    # Create an item
    resp = client.post('/api/v1/items', json={'name': 'Test Item', 'minQuantity': 5, 'targetQuantity': 10})
    print(f'Create item status: {resp.status_code}')
    if resp.status_code == 201:
        item_id = resp.get_json()['id']
        
        # Try the restocked endpoint with explicit method
        resp = client.post(f'/api/v1/restock/{item_id}/restocked', headers={'Authorization': token})
        print(f'Restocked status: {resp.status_code}')
        print(f'Restocked body: {resp.get_data(as_text=True)}')
        
        # Try with different URL patterns
        resp = client.post(f'/api/v1/restock/{item_id}/restocked', data='{}', content_type='application/json')
        print(f'Restocked (with data) status: {resp.status_code}')
        print(f'Restocked (with data) body: {resp.get_data(as_text=True)}')
