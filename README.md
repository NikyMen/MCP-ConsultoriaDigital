# MCP Consultoría Digital

Servidor MCP (Model Context Protocol) en Python que expone herramientas para el
**asistente comercial de Consultoría Digital**. Pensado para usarse desde
**n8n** (orquestador) + **GPT** (modelo) + **WaSender** (canal WhatsApp), con
deploy en VPS de Hostinger.

Es un servidor **sin estado**: ofrece a GPT información del catálogo de
productos y la validación de CUIT para calificar leads según el flujo comercial.
No persiste leads ni conversaciones — eso lo maneja n8n / el CRM si hace falta.

## Flujo

```
WhatsApp → WaSender → n8n → GPT (con MCP Client) → MCP Server (este repo)
                                                       │
                                                       ├─ productos / FAQs
                                                       └─ validar_cuit
```

## Productos

Definidos en [`data/productos.yaml`](data/productos.yaml) (editable sin tocar
código). Incluye descripción, FAQs y precios:

- `gestion_redes` — Gestión de Redes Sociales
- `pauta_meta` — Pauta Publicitaria en Meta
- `crm` — Automatización con CRM
- `concilia` — Conciliación bancaria con IA
- `turneria` — Software de turnos para salud

## Herramientas MCP expuestas

| Tool                            | Para qué sirve                                        |
| ------------------------------- | ----------------------------------------------------- |
| `productos_disponibles`         | Listar todos los productos.                           |
| `info_producto`                 | Descripción detallada + qué incluye + precio desde.   |
| `faqs_producto`                 | FAQs y respuestas oficiales del producto.             |
| `identificar_producto_interes`  | Inferir producto desde el mensaje del lead.           |
| `validar_cuit`                  | Validación de CUIT/CUIL argentino.                    |
| `recargar_catalogo`             | Recargar `productos.yaml` sin reiniciar el server.    |

## Estructura

```
.
├── server.py                # FastMCP server + bearer auth + middleware n8n
├── src/
│   ├── catalogo.py          # Carga del YAML
│   ├── config.py            # .env
│   └── cuit.py              # Validación CUIT
├── data/
│   └── productos.yaml       # ⇐ EDITAR precios y FAQs acá
├── deploy/
│   ├── consultoria-mcp.service
│   ├── nginx.conf.example
│   └── deploy.sh
└── n8n/
    └── workflow-ejemplo.md
```

## Desarrollo local

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; en Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # ajustar valores
python server.py
```

El server queda en `http://localhost:8765/mcp/`. Probalo con cualquier cliente
MCP (Claude Desktop con config HTTP, n8n MCP Client node, etc.).

## Deploy en VPS Hostinger (paso a paso)

### 1. Crear repo en GitHub y subir el código

```bash
cd D:\dev\MCP-ConsultoriaDigital
git init
git add .
git commit -m "Initial commit: MCP Consultoria Digital"
git branch -M main
git remote add origin git@github.com:TU_USUARIO/mcp-consultoria-digital.git
git push -u origin main
```

### 2. En el VPS (Ubuntu/Debian)

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git nginx
sudo mkdir -p /opt/mcp-consultoria && sudo chown $USER:$USER /opt/mcp-consultoria
git clone git@github.com:TU_USUARIO/mcp-consultoria-digital.git /opt/mcp-consultoria
cd /opt/mcp-consultoria

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

cp .env.example .env
# Editar .env con valores reales. Generar token largo:
#   openssl rand -hex 32
nano .env
```

### 3. Instalar service de systemd

```bash
sudo cp deploy/consultoria-mcp.service /etc/systemd/system/consultoria-mcp.service
# Editar si hace falta (User, paths)
sudo nano /etc/systemd/system/consultoria-mcp.service

sudo systemctl daemon-reload
sudo systemctl enable consultoria-mcp
sudo systemctl start consultoria-mcp
sudo systemctl status consultoria-mcp
```

### 4. Reverse proxy con Nginx + TLS

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/consultoria-mcp
sudo nano /etc/nginx/sites-available/consultoria-mcp   # ajustar dominio
sudo ln -s /etc/nginx/sites-available/consultoria-mcp /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Certificado TLS gratis:
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d tu-dominio.com
```

### 5. Conectar desde n8n

En n8n, agregar un nodo **MCP Client**:

- **URL**: `https://tu-dominio.com/mcp/`
- **Auth**: Header Auth → `Authorization: Bearer <MCP_AUTH_TOKEN>`
- **Tools**: cargar todas las del server.

Ver [`n8n/workflow-ejemplo.md`](n8n/workflow-ejemplo.md) para el detalle del
workflow completo (WaSender → AI Agent → MCP → respuesta).

### 6. Updates posteriores (un comando)

```bash
cd /opt/mcp-consultoria
bash deploy/deploy.sh
```

Hace `git pull`, reinstala deps y reinicia el service.

## Pendientes que tenés que completar

1. **Completar precios reales** en [`data/productos.yaml`](data/productos.yaml).
2. **Configurar `.env`** con datos reales de la empresa (CUIT, web, etc.) y
   generar un `MCP_AUTH_TOKEN` largo.
3. **Comprar dominio o subdominio** apuntando al VPS Hostinger.
4. **Workflow en n8n**: armar siguiendo `n8n/workflow-ejemplo.md`. Necesitás
   credenciales de WaSender y OpenAI configuradas en n8n.
