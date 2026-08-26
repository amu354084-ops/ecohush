from app.main import app
print("ROUTE COUNT", len(app.router.routes))
for index, r in enumerate(app.router.routes):
    print(
        "INDEX",
        index,
        type(r).__name__,
        getattr(r, "path", None),
        getattr(r, "name", None),
        getattr(r, "methods", None),
    )
    if type(r).__name__ == "_IncludedRouter":
        print("  ATTRS", [a for a in dir(r) if not a.startswith("_")])
        print("  ROUTES ATTR", hasattr(r, "routes"))
        print("  ROUTER ATTR", hasattr(r, "router"))
        print("  DEPTH", len(getattr(r, "routes", [])) if hasattr(r, "routes") else None)
        if hasattr(r, "routes"):
            for cr in getattr(r, "routes", [])[:10]:
                print(
                    "    CHILD",
                    type(cr).__name__,
                    getattr(cr, "path", None),
                    getattr(cr, "name", None),
                    getattr(cr, "methods", None),
                )
    print("---")
