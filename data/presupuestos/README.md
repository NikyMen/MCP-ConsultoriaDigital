# PDFs de presupuesto

Acá van los PDFs de presupuesto que el asistente manda por WhatsApp.

Guardá cada archivo con **exactamente** el nombre que figura en el campo
`archivo` de la sección `presupuestos:` de [`../productos.yaml`](../productos.yaml):

| Archivo                          | Cubre                                  |
| -------------------------------- | -------------------------------------- |
| `presupuesto-rrss-pauta.pdf`     | Gestión de Redes + Pauta en Meta       |
| `presupuesto-rrss-crm-pauta.pdf` | Redes + CRM + Pauta en Meta            |
| `presupuesto-concilia.pdf`       | Plataforma ConciliA                    |
| `presupuesto-turneria.pdf`       | TurnerIA (gestión de turnos)           |

El server los sirve como archivos estáticos en `/presupuestos/<archivo>` (ruta
pública, sin auth, para que WaSender pueda descargarlos por URL). Si configurás
`PRESUPUESTOS_BASE_URL` en `.env`, la tool `presupuesto_pdf` devuelve también la
URL completa lista para usar en n8n.

> Estos PDFs **no se versionan** en git (ver `.gitignore`): subilos al VPS a
> mano o por tu pipeline de deploy. Los precios viven solo acá dentro.
