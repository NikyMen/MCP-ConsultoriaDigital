"""Panel de administración web del MCP de Consultoría Digital.

Se monta dentro del mismo servidor Starlette (ver server.py) bajo el prefijo
``/admin``. Auth propia por contraseña (cookie de sesión firmada con HMAC),
independiente del bearer token del MCP.

Diseñado para escalar: agregar un módulo nuevo es (1) sumar una entrada a
``NAV`` y (2) registrar su Route en ``routes()``.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from . import catalogo, config, herramientas, leads

# ---------------------------------------------------------------------------
# Sesión / auth
# ---------------------------------------------------------------------------

COOKIE_NAME = "cd_admin"
SESSION_TTL = 7 * 24 * 3600  # 7 días


def _secret() -> bytes:
    base = config.ADMIN_SESSION_SECRET or f"{config.ADMIN_PASSWORD}|{config.MCP_AUTH_TOKEN}"
    return hashlib.sha256(base.encode("utf-8")).digest()


def _firmar(valor: str) -> str:
    sig = hmac.new(_secret(), valor.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{valor}.{sig}"


def _nueva_sesion() -> str:
    return _firmar(str(int(time.time())))


def _sesion_valida(cookie: str | None) -> bool:
    if not cookie or "." not in cookie:
        return False
    valor, sig = cookie.rsplit(".", 1)
    esperado = hmac.new(_secret(), valor.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, esperado):
        return False
    try:
        emitido = int(valor)
    except ValueError:
        return False
    return (time.time() - emitido) < SESSION_TTL


def _autenticado(request: Request) -> bool:
    return bool(config.ADMIN_PASSWORD) and _sesion_valida(request.cookies.get(COOKIE_NAME))


def _es_https(request: Request) -> bool:
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").lower() == "https"
    )


def _set_session_cookie(resp: Response, request: Request) -> None:
    resp.set_cookie(
        COOKIE_NAME,
        _nueva_sesion(),
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=_es_https(request),
        path="/admin",
    )


# ---------------------------------------------------------------------------
# Layout / helpers de render
# ---------------------------------------------------------------------------

NAV: list[tuple[str, str]] = [
    ("/admin", "Dashboard"),
    ("/admin/leads", "Leads"),
    ("/admin/herramientas", "Herramientas"),
]

ETAPA_COLOR = {
    "INICIAL": "#64748b",
    "PRODUCTO_IDENTIFICADO": "#0ea5e9",
    "MEDIA": "#f59e0b",
    "ALTA": "#22c55e",
    "DESCARTADO": "#ef4444",
}

_CSS = """
:root{--bg:#0f172a;--panel:#1e293b;--panel2:#273449;--line:#334155;--txt:#e2e8f0;
--muted:#94a3b8;--accent:#6366f1;--accent2:#818cf8}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:var(--bg);color:var(--txt);font-size:14px}
a{color:var(--accent2);text-decoration:none}
.shell{display:flex;min-height:100vh}
.side{width:220px;background:var(--panel);border-right:1px solid var(--line);
padding:20px 0;flex-shrink:0}
.brand{font-weight:700;font-size:16px;padding:0 20px 18px;border-bottom:1px solid var(--line)}
.brand small{display:block;color:var(--muted);font-weight:400;font-size:11px;margin-top:3px}
.nav a{display:block;padding:11px 20px;color:var(--muted);border-left:3px solid transparent}
.nav a:hover{background:var(--panel2);color:var(--txt)}
.nav a.active{color:#fff;border-left-color:var(--accent);background:var(--panel2)}
.nav .logout{margin-top:20px;border-top:1px solid var(--line);padding-top:14px}
.main{flex:1;padding:28px 34px;max-width:1100px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:30px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px}
.card .n{font-size:30px;font-weight:700}
.card .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em;margin-top:4px}
table{width:100%;border-collapse:collapse;background:var(--panel);border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:11px 14px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--panel2)}
.badge{display:inline-block;padding:3px 9px;border-radius:999px;font-size:11px;font-weight:600;color:#fff}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
.chip{padding:6px 13px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.chip.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.btn{display:inline-block;background:var(--accent);color:#fff;border:none;border-radius:8px;
padding:9px 16px;font-size:14px;cursor:pointer;font-weight:500}
.btn:hover{background:var(--accent2)}
.btn.ghost{background:transparent;border:1px solid var(--line);color:var(--txt)}
.btn.danger{background:#ef4444}
.row{display:flex;gap:24px;flex-wrap:wrap}
.col{flex:1;min-width:280px}
form.edit label{display:block;color:var(--muted);font-size:12px;margin:12px 0 5px}
input,select,textarea{width:100%;background:var(--bg);border:1px solid var(--line);
color:var(--txt);border-radius:8px;padding:9px 11px;font-size:14px;font-family:inherit}
textarea{min-height:80px;resize:vertical}
.panel-box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px}
.timeline{list-style:none;padding:0;margin:0}
.timeline li{padding:10px 0;border-bottom:1px solid var(--line)}
.timeline li:last-child{border-bottom:none}
.timeline .t{font-weight:600}
.timeline .d{color:var(--muted);font-size:12px}
.muted{color:var(--muted)}
.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
.login{display:flex;align-items:center;justify-content:center;min-height:100vh}
.login .box{background:var(--panel);border:1px solid var(--line);border-radius:14px;
padding:34px;width:340px}
.login h1{margin-bottom:6px}
.err{background:#7f1d1d;color:#fecaca;padding:10px 12px;border-radius:8px;margin:14px 0;font-size:13px}
.warn{background:#78350f;color:#fde68a;padding:10px 12px;border-radius:8px;margin:14px 0;font-size:13px}
.grp{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:18px}
.grp-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.grp-head h2{font-size:16px;margin:0}
.grp-desc{color:var(--muted);font-size:13px;margin:4px 0 14px}
.pill{display:inline-block;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600}
.pill.ok{background:#14532d;color:#86efac}
.pill.falta{background:#7f1d1d;color:#fecaca}
.pill.opcional{background:#1e3a5f;color:#93c5fd}
.pill.siempre{background:#334155;color:#cbd5e1}
.reqs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.req{font-size:11px;padding:3px 9px;border-radius:6px;border:1px solid var(--line);color:var(--muted)}
.req .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:middle}
.req .dot.on{background:#22c55e}.req .dot.off{background:#ef4444}.req .dot.opt{background:#64748b}
.tool{border-top:1px solid var(--line);padding:12px 0}
.tool:first-of-type{border-top:none}
.tool .name{font-family:ui-monospace,Menlo,Consolas,monospace;font-weight:600;color:#c7d2fe}
.tool .dsc{color:var(--muted);font-size:13px;margin:3px 0 0}
.params{margin:8px 0 0;display:flex;flex-direction:column;gap:4px}
.param{font-size:12px;color:var(--muted)}
.param code{font-family:ui-monospace,Menlo,Consolas,monospace;color:var(--txt)}
.param .ty{color:#7dd3fc}
.param .rq{color:#fca5a5;font-size:10px;text-transform:uppercase;letter-spacing:.04em;margin-left:4px}
.param .op{color:#64748b;font-size:10px;text-transform:uppercase;letter-spacing:.04em;margin-left:4px}
"""


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _badge(clasif: str | None) -> str:
    c = clasif or "INICIAL"
    color = ETAPA_COLOR.get(c, "#64748b")
    return f'<span class="badge" style="background:{color}">{_esc(c)}</span>'


def _layout(titulo: str, cuerpo: str, activo: str) -> str:
    nav = "".join(
        f'<a href="{href}" class="{"active" if href == activo else ""}">{_esc(label)}</a>'
        for href, label in NAV
    )
    return f"""<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(titulo)} · Consultoría Digital</title><style>{_CSS}</style></head>
<body><div class="shell">
<aside class="side">
  <div class="brand">Consultoría Digital<small>Panel MCP</small></div>
  <nav class="nav">{nav}
    <div class="logout"><a href="/admin/logout">Cerrar sesión</a></div>
  </nav>
</aside>
<main class="main">{cuerpo}</main>
</div></body></html>"""


def _redir_login() -> RedirectResponse:
    return RedirectResponse("/admin/login", status_code=302)


# ---------------------------------------------------------------------------
# Handlers: login
# ---------------------------------------------------------------------------

def _login_page(error: str = "", status: int = 200) -> HTMLResponse:
    aviso = ""
    if not config.ADMIN_PASSWORD:
        aviso = (
            '<div class="warn">No hay <b>ADMIN_PASSWORD</b> configurado en el .env. '
            "Configuralo y reiniciá el servicio para poder ingresar.</div>"
        )
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    html_doc = f"""<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ingresar · Consultoría Digital</title><style>{_CSS}</style></head>
<body><div class="login"><div class="box">
  <h1>Panel MCP</h1><p class="sub">Consultoría Digital</p>
  {aviso}{err}
  <form method="post" action="/admin/login">
    <label>Contraseña</label>
    <input type="password" name="password" autofocus required>
    <div style="margin-top:18px"><button class="btn" type="submit" style="width:100%">Ingresar</button></div>
  </form>
</div></div></body></html>"""
    return HTMLResponse(html_doc, status_code=status)


async def login(request: Request) -> Response:
    if request.method == "GET":
        if _autenticado(request):
            return RedirectResponse("/admin", status_code=302)
        return _login_page()

    form = await request.form()
    password = str(form.get("password", ""))
    if not config.ADMIN_PASSWORD:
        return _login_page("No hay contraseña configurada en el servidor.", status=503)
    if not hmac.compare_digest(password, config.ADMIN_PASSWORD):
        return _login_page("Contraseña incorrecta.", status=401)
    resp = RedirectResponse("/admin", status_code=302)
    _set_session_cookie(resp, request)
    return resp


async def logout(request: Request) -> Response:
    resp = RedirectResponse("/admin/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME, path="/admin")
    return resp


# ---------------------------------------------------------------------------
# Handlers: dashboard
# ---------------------------------------------------------------------------

ETAPAS_ORDEN = ["INICIAL", "PRODUCTO_IDENTIFICADO", "MEDIA", "ALTA", "DESCARTADO"]


async def dashboard(request: Request) -> Response:
    if not _autenticado(request):
        return _redir_login()

    conteo = leads.contar_por_clasificacion()
    total = leads.total()
    recientes = leads.listar(limit=10)

    cards = f'<div class="card"><div class="n">{total}</div><div class="l">Total leads</div></div>'
    for etapa in ETAPAS_ORDEN:
        n = conteo.get(etapa, 0)
        color = ETAPA_COLOR.get(etapa, "#64748b")
        cards += (
            f'<div class="card"><div class="n" style="color:{color}">{n}</div>'
            f'<div class="l">{_esc(etapa)}</div></div>'
        )

    filas = "".join(_fila_lead(l) for l in recientes) or (
        '<tr><td colspan="6" class="muted">Todavía no hay leads.</td></tr>'
    )
    cuerpo = f"""
<h1>Dashboard</h1><p class="sub">Resumen del pipeline comercial.</p>
<div class="cards">{cards}</div>
<div class="toolbar"><h1 style="font-size:17px">Últimos leads</h1>
  <a class="btn ghost" href="/admin/leads">Ver todos</a></div>
<table><thead><tr><th>#</th><th>Nombre</th><th>Empresa</th><th>Teléfono</th>
<th>Etapa</th><th>Actualizado</th></tr></thead><tbody>{filas}</tbody></table>
"""
    return HTMLResponse(_layout("Dashboard", cuerpo, "/admin"))


def _fila_lead(l: dict[str, Any]) -> str:
    return (
        f'<tr onclick="location=\'/admin/leads/{l["id"]}\'" style="cursor:pointer">'
        f'<td>{l["id"]}</td><td>{_esc(l.get("nombre")) or "—"}</td>'
        f'<td>{_esc(l.get("empresa")) or "—"}</td><td>{_esc(l.get("telefono")) or "—"}</td>'
        f'<td>{_badge(l.get("clasificacion"))}</td>'
        f'<td class="muted">{_esc((l.get("actualizado_en") or "")[:16].replace("T", " "))}</td></tr>'
    )


# ---------------------------------------------------------------------------
# Handlers: leads
# ---------------------------------------------------------------------------

async def lista_leads(request: Request) -> Response:
    if not _autenticado(request):
        return _redir_login()

    filtro = request.query_params.get("clasificacion") or None
    if filtro and filtro not in leads.VALIDAS:
        filtro = None
    items = leads.listar(clasificacion=filtro, limit=300)

    chips = f'<a class="chip {"active" if not filtro else ""}" href="/admin/leads">Todos</a>'
    for etapa in ETAPAS_ORDEN:
        cls = "active" if filtro == etapa else ""
        chips += f'<a class="chip {cls}" href="/admin/leads?clasificacion={etapa}">{_esc(etapa)}</a>'

    filas = "".join(_fila_lead(l) for l in items) or (
        '<tr><td colspan="6" class="muted">Sin resultados.</td></tr>'
    )
    cuerpo = f"""
<div class="toolbar"><div><h1>Leads</h1><p class="sub">{len(items)} lead(s).</p></div>
  <a class="btn" href="/admin/leads/nuevo">+ Nuevo lead</a></div>
<div class="chips">{chips}</div>
<table><thead><tr><th>#</th><th>Nombre</th><th>Empresa</th><th>Teléfono</th>
<th>Etapa</th><th>Actualizado</th></tr></thead><tbody>{filas}</tbody></table>
"""
    return HTMLResponse(_layout("Leads", cuerpo, "/admin/leads"))


def _opciones_clasif(actual: str | None) -> str:
    return "".join(
        f'<option value="{e}" {"selected" if e == actual else ""}>{e}</option>'
        for e in ETAPAS_ORDEN
    )


def _opciones_producto(actual: str | None) -> str:
    opts = f'<option value="" {"selected" if not actual else ""}>— sin definir —</option>'
    for clave in catalogo.claves_productos():
        nombre = (catalogo.producto(clave) or {}).get("nombre", clave)
        sel = "selected" if clave == actual else ""
        opts += f'<option value="{_esc(clave)}" {sel}>{_esc(nombre)}</option>'
    return opts


def _form_lead(l: dict[str, Any], accion: str, nuevo: bool = False) -> str:
    return f"""
<form class="edit" method="post" action="{accion}">
  <div class="row">
    <div class="col">
      <label>Nombre</label><input name="nombre" value="{_esc(l.get('nombre'))}">
      <label>Empresa</label><input name="empresa" value="{_esc(l.get('empresa'))}">
      <label>Teléfono / wa_id</label><input name="telefono" value="{_esc(l.get('telefono'))}">
      <label>CUIT / CUIL</label><input name="cuit" value="{_esc(l.get('cuit'))}">
    </div>
    <div class="col">
      <label>Producto de interés</label>
      <select name="producto_interes">{_opciones_producto(l.get('producto_interes'))}</select>
      <label>Clasificación</label>
      <select name="clasificacion">{_opciones_clasif(l.get('clasificacion') or 'INICIAL')}</select>
      <label>Notas</label><textarea name="notas">{_esc(l.get('notas'))}</textarea>
    </div>
  </div>
  <div style="margin-top:18px;display:flex;gap:10px">
    <button class="btn" type="submit">{'Crear lead' if nuevo else 'Guardar cambios'}</button>
    <a class="btn ghost" href="/admin/leads">Cancelar</a>
  </div>
</form>"""


async def nuevo_lead(request: Request) -> Response:
    if not _autenticado(request):
        return _redir_login()
    if request.method == "POST":
        form = await request.form()
        lead = leads.upsert(
            telefono=(str(form.get("telefono")).strip() or None),
            nombre=(str(form.get("nombre")).strip() or None),
            empresa=(str(form.get("empresa")).strip() or None),
            cuit=(str(form.get("cuit")).strip() or None),
            producto_interes=(str(form.get("producto_interes")).strip() or None),
            clasificacion=(str(form.get("clasificacion")).strip() or "INICIAL"),
            notas=(str(form.get("notas")).strip() or None),
        )
        leads.registrar_evento(lead["id"], "creado_panel", "alta manual desde el panel")
        return RedirectResponse(f"/admin/leads/{lead['id']}", status_code=302)

    cuerpo = f'<h1>Nuevo lead</h1><p class="sub">Alta manual.</p><div class="panel-box">{_form_lead({}, "/admin/leads/nuevo", nuevo=True)}</div>'
    return HTMLResponse(_layout("Nuevo lead", cuerpo, "/admin/leads"))


async def detalle_lead(request: Request) -> Response:
    if not _autenticado(request):
        return _redir_login()
    lead_id = int(request.path_params["lead_id"])
    lead = leads.obtener(lead_id)
    if not lead:
        return HTMLResponse(_layout("No encontrado", "<h1>Lead no encontrado</h1>", "/admin/leads"), status_code=404)

    evs = leads.eventos(lead_id)
    presus = leads.presupuestos(lead_id)

    tl = "".join(
        f'<li><div class="t">{_esc(e.get("tipo"))}</div>'
        f'<div class="muted">{_esc(e.get("detalle")) or ""}</div>'
        f'<div class="d">{_esc((e.get("creado_en") or "")[:19].replace("T", " "))}</div></li>'
        for e in evs
    ) or '<li class="muted">Sin eventos.</li>'

    if presus:
        pr = "".join(
            '<li><div class="t">#{prod} · ${total}</div>'.format(
                prod=_esc(p.get("producto")), total=_esc(p.get("total_ars"))
            )
            + (
                f'<div class="d"><a href="{_esc(p.get("url_publica"))}" target="_blank">Ver PDF</a></div>'
                if p.get("url_publica")
                else f'<div class="d muted">{_esc(p.get("archivo"))}</div>'
            )
            + f'<div class="d">{_esc((p.get("creado_en") or "")[:19].replace("T", " "))}</div></li>'
            for p in presus
        )
    else:
        pr = '<li class="muted">Sin presupuestos.</li>'

    titulo_lead = _esc(lead.get("empresa") or lead.get("nombre") or f"Lead #{lead_id}")
    cuerpo = f"""
<div class="toolbar">
  <div><h1>{titulo_lead} {_badge(lead.get('clasificacion'))}</h1>
  <p class="sub">Lead #{lead_id} · creado {_esc((lead.get('creado_en') or '')[:16].replace('T', ' '))}</p></div>
  <form method="post" action="/admin/leads/{lead_id}/eliminar"
        onsubmit="return confirm('¿Eliminar este lead y todo su historial?')">
    <button class="btn danger" type="submit">Eliminar</button></form>
</div>
<div class="row">
  <div class="col" style="flex:1.4">
    <div class="panel-box">{_form_lead(lead, f"/admin/leads/{lead_id}")}</div>
  </div>
  <div class="col">
    <div class="panel-box" style="margin-bottom:18px">
      <h1 style="font-size:15px">Presupuestos</h1>
      <ul class="timeline">{pr}</ul>
    </div>
    <div class="panel-box">
      <h1 style="font-size:15px">Historial</h1>
      <ul class="timeline">{tl}</ul>
    </div>
  </div>
</div>
"""
    return HTMLResponse(_layout(titulo_lead, cuerpo, "/admin/leads"))


async def guardar_lead(request: Request) -> Response:
    if not _autenticado(request):
        return _redir_login()
    lead_id = int(request.path_params["lead_id"])
    if not leads.obtener(lead_id):
        return HTMLResponse("Lead no encontrado", status_code=404)
    form = await request.form()
    clasif = str(form.get("clasificacion", "")).strip() or "INICIAL"
    if clasif not in leads.VALIDAS:
        clasif = "INICIAL"
    leads.actualizar(
        lead_id,
        telefono=(str(form.get("telefono")).strip() or None),
        nombre=(str(form.get("nombre")).strip() or None),
        empresa=(str(form.get("empresa")).strip() or None),
        cuit=(str(form.get("cuit")).strip() or None),
        producto_interes=(str(form.get("producto_interes")).strip() or None),
        clasificacion=clasif,
        notas=(str(form.get("notas")).strip() or None),
    )
    leads.registrar_evento(lead_id, "editado_panel", f"clasificacion={clasif}")
    return RedirectResponse(f"/admin/leads/{lead_id}", status_code=302)


async def eliminar_lead(request: Request) -> Response:
    if not _autenticado(request):
        return _redir_login()
    lead_id = int(request.path_params["lead_id"])
    leads.eliminar(lead_id)
    return RedirectResponse("/admin/leads", status_code=302)


# ---------------------------------------------------------------------------
# Handlers: herramientas (tools MCP)
# ---------------------------------------------------------------------------

_PILL_LABEL = {
    "ok": "Configurada",
    "falta": "Falta configurar",
    "opcional": "Lista (ajustes opcionales)",
    "siempre": "Siempre disponible",
}


def _render_requisitos(reqs: list[tuple[str, bool, bool]]) -> str:
    if not reqs:
        return ""
    items = ""
    for etiqueta, presente, opcional in reqs:
        if opcional:
            dot = "opt" if not presente else "on"
        else:
            dot = "on" if presente else "off"
        suf = " (opcional)" if opcional else ""
        items += f'<span class="req"><span class="dot {dot}"></span>{_esc(etiqueta)}{suf}</span>'
    return f'<div class="reqs">{items}</div>'


def _render_params(params: list[dict[str, Any]]) -> str:
    if not params:
        return '<div class="param muted">Sin parámetros.</div>'
    filas = ""
    for p in params:
        flag = '<span class="rq">requerido</span>' if p["requerido"] else '<span class="op">opcional</span>'
        desc = f' — {_esc(p["descripcion"])}' if p["descripcion"] else ""
        filas += (
            f'<div class="param"><code>{_esc(p["nombre"])}</code> '
            f'<span class="ty">{_esc(p["tipo"])}</span>{flag}{desc}</div>'
        )
    return f'<div class="params">{filas}</div>'


async def herramientas_page(request: Request) -> Response:
    if not _autenticado(request):
        return _redir_login()

    # Lista viva de tools desde el server MCP (introspección en runtime).
    import server  # import diferido: evita el ciclo admin <-> server

    tools = await server.mcp.list_tools()
    por_grupo: dict[str, list[Any]] = {}
    for t in tools:
        por_grupo.setdefault(herramientas.grupo_de(t.name), []).append(t)

    total = len(tools)
    secciones = ""
    for grupo in herramientas.GRUPOS:
        items = sorted(por_grupo.get(grupo["clave"], []), key=lambda t: t.name)
        if not items:
            continue
        est = herramientas.estado_grupo(grupo["requisitos"])
        estado = est["estado"]
        pill = f'<span class="pill {estado}">{_PILL_LABEL[estado]}</span>'

        tools_html = ""
        for t in items:
            params = herramientas.extraer_parametros(t.parameters or {})
            tools_html += (
                f'<div class="tool"><div class="name">{_esc(t.name)}</div>'
                f'<p class="dsc">{_esc(t.description or "")}</p>'
                f'{_render_params(params)}</div>'
            )

        secciones += f"""
<section class="grp">
  <div class="grp-head"><h2>{_esc(grupo["nombre"])}</h2>{pill}
    <span class="muted" style="font-size:12px">{len(items)} tool(s)</span></div>
  <p class="grp-desc">{_esc(grupo["descripcion"])}</p>
  {_render_requisitos(est["requisitos"])}
  {tools_html}
</section>"""

    cuerpo = f"""
<h1>Herramientas</h1>
<p class="sub">{total} herramientas MCP expuestas al agente. La configuración se ajusta en el <code>.env</code>.</p>
{secciones}
"""
    return HTMLResponse(_layout("Herramientas", cuerpo, "/admin/herramientas"))


# ---------------------------------------------------------------------------
# Registro de rutas
# ---------------------------------------------------------------------------

def routes() -> list[Route]:
    return [
        Route("/admin/login", login, methods=["GET", "POST"]),
        Route("/admin/logout", logout, methods=["GET"]),
        Route("/admin", dashboard, methods=["GET"]),
        Route("/admin/herramientas", herramientas_page, methods=["GET"]),
        Route("/admin/leads", lista_leads, methods=["GET"]),
        Route("/admin/leads/nuevo", nuevo_lead, methods=["GET", "POST"]),
        Route("/admin/leads/{lead_id:int}", detalle_lead, methods=["GET"]),
        Route("/admin/leads/{lead_id:int}", guardar_lead, methods=["POST"]),
        Route("/admin/leads/{lead_id:int}/eliminar", eliminar_lead, methods=["POST"]),
    ]
