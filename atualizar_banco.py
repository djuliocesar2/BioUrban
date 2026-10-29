from app import app, db

with app.app_context():
    with db.engine.connect() as conn:
        try:
            conn.execute(db.text("ALTER TABLE hortalica ADD COLUMN umidade_min FLOAT DEFAULT 40.0;"))
            conn.execute(db.text("ALTER TABLE hortalica ADD COLUMN umidade_max FLOAT DEFAULT 70.0;"))
            conn.commit()
            print("Sucesso! Colunas umidade_min e umidade_max adicionadas no banco de dados.")
        except Exception as e:
            print(f"Aviso/Resultado: {e}")