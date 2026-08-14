# 🚗 Cotizador Mazda MX (automatizado)

Script que consulta el **cotizador oficial de Mazda Financial Services / Santander** (`mazdafinancialservices.mx/TekFinauto`) y extrae las cuotas de financiamiento reales para un vehículo, enganche y plazo dados.

## ¿Qué hace?

1. Abre el cotizador real (el mismo que usa mazda.mx)
2. Selecciona estado → distribuidor → modelo → versión → año → plan financiero
3. Fija el enganche deseado (en $ o %)
4. Llena los datos personales requeridos con **datos ficticios** (el sitio los exige para calcular; el cálculo aparece ANTES del código de verificación por correo/SMS)
5. Pulsa "MOSTRAR CUOTAS" y extrae la tabla de cuotas (12–72 meses)
6. Devuelve JSON con el valor del vehículo, enganche, plan y todas las cuotas

## Uso local

```bash
# instalación (una vez)
python -m venv .venv
source .venv/bin/activate
pip install playwright==1.62.0
playwright install chromium

# cotización por defecto: CX-5 Grand Touring 2WD 2026, enganche $200,000
python cotizar.py

# personalizada
python cotizar.py \
  --modelo "MAZDA CX-30" \
  --version "MAZDA CX-30 I GRAND TOURING 2WD" \
  --anio 2026 \
  --enganche 150000 \
  --estado HIDALGO \
  --distribuidor "MAZDA PACHUCA"

# filtrar un plazo y guardar a archivo
python cotizar.py --plazo 36 --json resultados.json
```

### Opciones

| Opción | Default | Descripción |
|---|---|---|
| `--modelo` | `MAZDA CX-5` | Modelo exacto como aparece en el cotizador |
| `--version` | `MAZDA CX-5 I GRAND TOURING 2WD` | Versión exacta |
| `--anio` | `2026` | Año modelo |
| `--enganche` | `200000` | Enganche en MXN |
| `--estado` | `HIDALGO` | Estado (carga el distribuidor) |
| `--distribuidor` | *(primero disponible)* | Distribuidor específico |
| `--plazo` | *(todos)* | Filtrar solo un plazo (ej. 36) |
| `--json` | *(stdout)* | Guardar resultado en archivo JSON |

## Ejemplo de salida

```json
{
  "fuente": "mazdafinancialservices.mx/TekFinauto (cotizador oficial)",
  "consulta": {
    "estado": "HIDALGO",
    "distribuidor": "MAZDA PACHUCA",
    "modelo": "MAZDA CX-5",
    "version": "MAZDA CX-5 I GRAND TOURING 2WD",
    "anio": 2026,
    "plan": "MAZDA FLEX SUV TASA 13.49 %",
    "valor_vehiculo": 659900.0,
    "enganche": 200015.69,
    "enganche_porcentaje": "30.31%"
  },
  "cuotas": [
    {"plazo_meses": 12, "cuota_mensual": 41182.82},
    {"plazo_meses": 36, "cuota_mensual": 15604.08}
  ]
}
```

## Automatización con GitHub Actions

El workflow incluido (`.github/workflows/cotizar.yml`) corre el script **cada lunes a las 08:00 CDMX** y guarda el resultado en `resultados.json` del repo. También se puede disparar manualmente desde la pestaña **Actions → Cotizar Mazda → Run workflow**.

**Para usarlo en tu repo:**
1. Copia `cotizar.py`, `requirements.txt` y `.github/workflows/cotizar.yml` a tu repo
2. Ajusta los argumentos del workflow a lo que quieras cotizar
3. Listo — el lunes siguiente tendrás `resultados.json` actualizado

## ⚠️ Advertencias

- **No es una integración oficial.** Automatiza el sitio público de Mazda/Santander; puede romperse si cambian la web o bloquear la IP. Uso personal recomendado.
- Las cuotas son **aproximadas** (así lo dice el propio cotizador) y **no incluyen seguro** de daños ni coberturas adicionales.
- El enganche puede redondearse al paso del slider del sitio (~$15 MXN), lo que varía la cuota en centavos.
- Se usan datos personales ficticios solo para pasar la validación; el cálculo se muestra antes del código de verificación.

## Verificación

El cálculo del script coincide con la fórmula estándar de amortización:

```
cuota = P · r · (1+r)ⁿ / ((1+r)ⁿ − 1)   (r = tasa mensual, n = meses)
```

Verificado contra el cotizador real: diferencia de $0.00 en los 6 plazos.
