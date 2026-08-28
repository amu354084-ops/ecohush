# Database migrations

Apply the baseline once, then create and review a migration for every schema
change before deploying an application update.

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe the schema change"
alembic upgrade head
```

Always create a backup before applying a production migration.
