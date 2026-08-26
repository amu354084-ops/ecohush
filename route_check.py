from app.main import app
print("cwd", __import__("os").getcwd())
print("route count", len(app.router.routes))
for r in app.router.routes:
    print(
        type(r).__name__,
        getattr(r, "path", None),
        getattr(r, "name", None),
        getattr(r, "methods", None),
    )
    if type(r).__name__ == "_IncludedRouter":
        sub = getattr(r, "router", None)
        if sub is not None:
            print("  child count", len(getattr(sub, "routes", [])))
            for cr in getattr(sub, "routes", [])[:10]:
                print(
                    "   child",
                    type(cr).__name__,
                    getattr(cr, "path", None),
                    getattr(cr, "name", None),
                    getattr(cr, "methods", None),
                )
