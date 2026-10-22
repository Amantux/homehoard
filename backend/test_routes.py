from app import create_app

app = create_app()
with app.app_context():
    # Check all routes
    for rule in app.url_map.iter_rules():
        print(f'{rule.methods} {rule} -> {rule.endpoint}')
