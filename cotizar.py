#!/usr/bin/env python3
"""
Cotizador Mazda MX — consulta el cotizador real de Mazda Financial Services
(Santander "Súper Auto") y extrae las cuotas de financiamiento.

Uso:
    python cotizar.py                              # defaults: CX-5 GT, 2026, enganche $200k
    python cotizar.py --modelo "MAZDA CX-30" --version "MAZDA CX-30 I GRAND TOURING 2WD" \
                      --anio 2026 --enganche 150000 --estado HIDALGO
    python cotizar.py --enganche 200000 --plazo 36   # filtra solo el plazo pedido
    python cotizar.py --json salida.json              # guarda el JSON completo

Requiere: pip install playwright && playwright install chromium
Env vars opcionales: PLAYWRIGHT_BROWSERS_PATH (ruta de browsers de playwright)
"""
import argparse
import json
import re
import sys
import time

from playwright.sync_api import sync_playwright

URL_COTIZADOR = (
    "https://www.mazdafinancialservices.mx/TekFinauto/Cotizador/vehiculo"
    "?financialProduct=2&productType=2&use=2&personType=2&idbrand=2"
)

# Datos personales ficticios: el cotizador los exige para calcular cuotas
# (el cálculo se muestra ANTES del código de verificación por correo/SMS)
DATOS_FICTICIOS = {
    "txtfName": "Juan",
    "txtsName": "Carlos",
    "txtflastName": "Prueba",
    "txtsLastName": "Demo",
    "txtTelephoneLada": "771",
    "txtTelephone": "1234-567",
    "txtCelphone": "771-111-1111",
    "txtMail": "cotizacion.demo@example.com",
    "txdBirthDate": "01/01/1990",
}


def log(msg: str) -> None:
    print(f"[cotizar] {msg}", file=sys.stderr, flush=True)


def select_option(page, selector: str, texto: str, intentos: int = 15) -> bool:
    """Selecciona una <option> por su texto, esperando a que cargue (AJAX)."""
    for i in range(intentos):
        opts = page.eval_on_selector_all(
            f"{selector} option", "els => els.map(e => e.textContent.trim())"
        )
        if texto.upper() in [o.upper() for o in opts]:
            page.select_option(selector, label=texto)
            page.wait_for_timeout(600)  # deja que el AJAX de campos dependientes corra
            return True
        time.sleep(1)
    disponibles = page.eval_on_selector_all(
        f"{selector} option", "els => els.map(e => e.textContent.trim())"
    )
    log(f"  ! no encontré '{texto}' en {selector}; opciones: {disponibles[:12]}")
    return False


def set_enganche(page, monto: int, valor_vehiculo: float | None = None) -> bool:
    """Fija el enganche en $ con reintentos (el slider se reinicia tras cargar el plan)."""
    pct = (monto / valor_vehiculo * 100) if valor_vehiculo else None
    for intento in range(8):
        ok = page.evaluate(
            """({monto, pct}) => {
                const $ = window.jQuery;
                if (!$ || !$('#slider-enganche').data('ionRangeSlider')) return false;
                $('#slider-enganche').data('ionRangeSlider').update({from: monto});
                $('#slider-enganche').trigger('change');
                $('#slider-enganche').trigger('input');
                // también escribir directo los campos visibles
                const m = document.getElementById('valor-slider-enganche');
                const p = document.getElementById('porcentaje-elemento');
                if (m) { m.value = monto.toFixed(2); m.dispatchEvent(new Event('change', {bubbles:true})); m.dispatchEvent(new Event('blur', {bubbles:true})); }
                if (p && pct) { p.value = pct.toFixed(2) + '%'; p.dispatchEvent(new Event('change', {bubbles:true})); p.dispatchEvent(new Event('blur', {bubbles:true})); }
                return true;
            }""",
            {"monto": monto, "pct": pct},
        )
        if not ok:
            log("  ! no pude usar el slider ionRangeSlider")
            return False
        page.wait_for_timeout(1000)
        val = page.input_value("#valor-slider-enganche")
        limpio = float(re.sub(r"[^\d.]", "", val)) if re.search(r"\d", val) else 0.0
        log(f"  intento {intento+1}: campo enganche = {val}")
        # tolerancia: el slider redondea al paso del sitio (~$15)
        if abs(limpio - monto) < 100.0:
            return True
    log(f"  ! el enganche no quedó en {monto:,.0f}; continúo con lo que haya")
    return True


def extraer_cuotas(page) -> list[dict]:
    """Extrae la tabla de cuotas del div #divTerms (aparece oculto y se llena vía AJAX)."""
    page.wait_for_selector("#divTerms", state="attached", timeout=30000)
    # esperar a que aparezca contenido real (no solo la leyenda)
    for _ in range(25):
        txt = page.eval_on_selector("#divTerms", "el => el.innerText")
        if re.search(r"\$\d", txt):
            break
        time.sleep(1)
    txt = page.eval_on_selector("#divTerms", "el => el.innerText")
    # patrón: $12,345.67 MXN \n 36 Meses
    pares = re.findall(r"\$([\d,.]+) MXN\s*\n\s*(\d+)\s*Meses", txt)
    return [{"plazo_meses": int(m), "cuota_mensual": float(p.replace(",", ""))} for p, m in pares]


def cotizar(args) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        log(f"abriendo cotizador: {URL_COTIZADOR}")
        page.goto(URL_COTIZADOR, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        # --- Estado / distribuidor ---
        log(f"seleccionando estado: {args.estado}")
        if not select_option(page, "#cboState", args.estado):
            raise RuntimeError("estado no disponible")
        # el distribuidor carga vía AJAX; elegir el primero (o el pedido)
        if args.distribuidor:
            if not select_option(page, "#cboDistributor", args.distribuidor):
                raise RuntimeError(f"distribuidor no disponible: {args.distribuidor}")
        else:
            page.wait_for_timeout(1500)
            n = page.eval_on_selector("#cboDistributor", "el => el.options.length")
            if n > 1:
                page.select_option("#cboDistributor", index=1)
                page.wait_for_timeout(600)
                dist = page.eval_on_selector(
                    "#cboDistributor", "el => el.options[el.selectedIndex].text"
                )
                log(f"distribuidor: {dist}")
            else:
                raise RuntimeError("no cargó ningún distribuidor")

        # --- Producto ---
        log(f"modelo: {args.modelo}")
        if not select_option(page, "#cboProduct", args.modelo):
            raise RuntimeError("modelo no disponible")
        log(f"versión: {args.version}")
        if not select_option(page, "#cboVersion", args.version):
            raise RuntimeError("versión no disponible")
        log(f"año: {args.anio}")
        if not select_option(page, "#cboYear", str(args.anio)):
            raise RuntimeError("año no disponible")

        # --- Plan financiero ---
        page.wait_for_timeout(1500)
        n_planes = page.eval_on_selector("#cboFinantialPlan", "el => el.options.length")
        if n_planes > 1:
            page.select_option("#cboFinantialPlan", index=1)
            page.wait_for_timeout(800)
            plan = page.eval_on_selector(
                "#cboFinantialPlan", "el => el.options[el.selectedIndex].text"
            )
            log(f"plan: {plan}")
        else:
            raise RuntimeError("no cargó ningún plan financiero")

        # --- Valor del vehículo (leer ANTES del enganche para calcular el %) ---
        valor_vehiculo = None
        for _ in range(10):
            try:
                raw = page.input_value("#input-as-label-operator", timeout=1500)
                if re.search(r"\d", raw):
                    valor_vehiculo = float(re.sub(r"[^\d.]", "", raw))
                    break
            except Exception:
                pass
            page.wait_for_timeout(1000)
        if valor_vehiculo:
            log(f"valor del vehículo: ${valor_vehiculo:,.2f}")
        else:
            log("  ! no pude leer el valor del vehículo")

        # --- Enganche ---
        log(f"enganche: ${args.enganche:,.0f}")
        if not set_enganche(page, args.enganche, valor_vehiculo):
            raise RuntimeError("no pude fijar el enganche")
        pct = page.input_value("#porcentaje-elemento")
        log(f"  ({pct} del valor del vehículo)")

        # --- Datos personales ficticios ---
        # OJO: el sitio ejecuta ResetSimulationWithoutHide() al cambiar estado/modelo/plan,
        # lo que BORRA los datos del solicitante. Por eso se llenan al final, antes de cotizar.
        log("llenando datos personales (ficticios)")
        for campo, valor_campo in DATOS_FICTICIOS.items():
            try:
                page.fill(f"#{campo}", valor_campo)
            except Exception as e:
                log(f"  ! campo {campo}: {e}")
        # radio custom oculto por CSS: click vía JS (como hace el sitio)
        page.evaluate("""() => { const r = document.getElementById('rdoMale'); r.click(); }""")
        page.select_option("#cboScheduleContact", index=1)
        page.wait_for_timeout(300)

        # --- MOSTRAR CUOTAS ---
        log("pulsando MOSTRAR CUOTAS")
        page.click("#btnCalcCuotas")
        page.wait_for_timeout(2000)

        # cerrar modales de avisos si aparecen
        for _ in range(5):
            modales = page.eval_on_selector_all(
                ".modal, [class*=modal], [role=dialog]",
                "els => els.filter(e => e.offsetParent !== null).length",
            )
            if not modales:
                break
            page.evaluate(
                """() => {
                    const modals = [...document.querySelectorAll('.modal, [class*=modal], [role=dialog]')]
                        .filter(m => m.offsetParent !== null);
                    modals.forEach(m => {
                        [...m.querySelectorAll('button')].forEach(b => {
                            if (/ACEPTAR|OK|SI/i.test(b.innerText.trim())) b.click();
                        });
                    });
                }"""
            )
            page.wait_for_timeout(1200)

        cuotas = extraer_cuotas(page)
        log(f"cuotas obtenidas: {len(cuotas)} plazos")

        # debug: capturar estado si no hay cuotas
        if not cuotas:
            page.screenshot(path="debug_no_cuotas.png", full_page=True)
            dump = page.eval_on_selector_all(
                ".modal, [class*=modal], [role=dialog], .alert, .has-error",
                "els => els.filter(e => e.offsetParent !== null).map(e => e.innerText.trim().slice(0,200))",
            )
            term_txt = page.eval_on_selector("#divTerms", "el => el.innerText")
            log(f"  DEBUG modales/errores visibles: {dump}")
            log(f"  DEBUG divTerms: {term_txt[:300]!r}")

        # datos de contexto de la página
        try:
            monto_enganche = page.input_value("#valor-slider-enganche")
            monto_enganche = float(re.sub(r"[^\d.]", "", monto_enganche))
        except Exception:
            monto_enganche = None
        try:
            version = page.eval_on_selector(
                "#cboVersion", "el => el.options[el.selectedIndex].text"
            )
        except Exception:
            version = args.version

        browser.close()

        return {
            "fuente": "mazdafinancialservices.mx/TekFinauto (cotizador oficial)",
            "fecha": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "consulta": {
                "estado": args.estado,
                "distribuidor": dist if "dist" in dir() else args.distribuidor,
                "modelo": args.modelo,
                "version": version,
                "anio": args.anio,
                "plan": plan if "plan" in dir() else None,
                "valor_vehiculo": valor_vehiculo,
                "enganche": float(monto_enganche) if monto_enganche else args.enganche,
                "enganche_porcentaje": pct if "pct" in dir() else None,
            },
            "cuotas": cuotas,
            "nota": "Cuotas aproximadas; no incluyen seguro de daños ni coberturas adicionales. "
                    "Datos personales ficticios; el cálculo se muestra antes del código de verificación.",
        }


def main():
    ap = argparse.ArgumentParser(description="Cotizador automático Mazda MX")
    ap.add_argument("--modelo", default="MAZDA CX-5", help="modelo (ej. 'MAZDA CX-5')")
    ap.add_argument("--version", default="MAZDA CX-5 I GRAND TOURING 2WD")
    ap.add_argument("--anio", type=int, default=2026)
    ap.add_argument("--enganche", type=float, default=200000)
    ap.add_argument("--estado", default="HIDALGO")
    ap.add_argument("--distribuidor", default=None)
    ap.add_argument("--plazo", type=int, default=None, help="filtrar solo este plazo")
    ap.add_argument("--json", default=None, help="ruta del archivo JSON de salida")
    args = ap.parse_args()

    resultado = cotizar(args)

    if args.plazo:
        for c in resultado["cuotas"]:
            if c["plazo_meses"] == args.plazo:
                resultado["plazo_seleccionado"] = c
                break

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
        log(f"guardado en {args.json}")


if __name__ == "__main__":
    main()
