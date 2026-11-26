# Verificación de flota en la recepción del hub

> 2026-11-24. Cierra la última deuda: el hub aceptaba hechos de cualquiera con
> una clave válida. Código: `hechos_wire::recibir_hechos_de_flota`

---

## 1 · El agujero

**Antes**, el hub comprobaba:

| Comprobación | Qué garantiza |
|---|---|
| Cadena de hashes | no falta ni sobra ningún hecho |
| Sello de bloque | nadie manipuló las 100 muestras |
| Firma Ed25519 | **alguien con esta clave** lo firmó |

Con eso, un atacante podía:

1. Generarse un par Ed25519.
2. Escribir 300 muestras encadenadas y firmadas correctamente.
3. Mandarlas al hub.

**Y el hub las aceptaba.**

La criptografía estaba impecable. Faltaba la confianza: *¿esa clave es de un
barco de mi flota?*

## 2 · Lo que faltaba, y no era código

`verificar_serie_de_flota` **ya existía** y estaba probada desde hace días, con
los 5 casos (flota propia, flota ajena, certificado prestado, nombre cambiado,
suplantación). Lo que faltaba era que **el certificado viajara por el cable**: el
hub no lo recibía, así que no podía comprobar nada.

## 3 · La pieza nueva

El certificado va **antes de los hechos**, con prefijo `CERT|` dentro de un
mensaje `DATA`:

```rust
pub fn mensaje_de_certificado(c: &CertificadoFlota) -> DdpMessage
pub fn certificado_de_mensaje(msg: &DdpMessage) -> Option<CertificadoFlota>
pub fn separar_certificado(msgs: &[DdpMessage]) -> (Option<CertificadoFlota>, Vec<DdpMessage>)
```

**Por qué un prefijo y no un tipo DDP nuevo:** los cinco tipos están fijados en la
spec. Añadir uno obligaría a cambiar el protocolo y el cable. Un prefijo dentro de
un `DATA` resuelve lo mismo sin tocar nada.

**Por qué el certificado va primero:** el hub necesita la clave del barco para
verificar. Si los hechos llegaran antes, tendría que guardarlos sin verificar o
rechazarlos.

## 4 · La recepción, en orden

```rust
recibir_hechos_de_flota(host, mensajes, raiz_del_armador, bloque, firma_por_hecho)
```

1. **¿Vino certificado?** Si no, se rechaza toda la tanda.
2. **¿Está firmado por la raíz del armador?** Si no, se rechaza.
3. **¿La clave del certificado es la que firma?**
4. **¿Los hechos son de ESE barco?** Si el certificado es de A y los hechos dicen
   B, se rechaza.
5. Cadena, sellos y guardado, con la clave ya validada.

## 5 · Verificado

```
[OK] barco de la flota                     -> aceptados=5  guardados=5
[OK] clave valida SIN certificado          -> aceptados=0  guardados=0
     motivo: "sin certificado de flota: no se puede verificar la pertenencia"
[OK] certificado de OTRA flota             -> aceptados=0  rechazados=5
[OK] certificado de A, hechos de B         -> aceptados=0  rechazados=5
[OK] el certificado va y vuelve por el cable
```

**210 tests en `lumen-nodo`, todos verdes.**

## 6 · La frase que esto cambia

| Antes | Ahora |
|---|---|
| *"alguien con esta clave firmó esto"* | *"**esta clave es de un barco de mi flota, y ese barco es el que dice ser**"* |

Y la segunda mitad importa tanto como la primera: **un barco de la flota no puede
firmar a nombre de otro**. Su clave es legítima y su certificado es real, pero los
hechos dicen otro nombre y se rechazan.

## 7 · Lo que sigue sin cubrir

- **El hub de la simulación no usa esta función todavía.** `sim_flota.rs` sigue
  con `recibir_hechos` porque los barcos de simulación no llevan certificado. La
  función está lista y probada; conectarla exige que `sim_flota` emita
  certificados, que es trabajo de la simulación, no del protocolo.
- **Revocación de certificados.** Si un barco se compromete, hoy no hay forma de
  retirarle el certificado sin cambiar la raíz.
- **El certificado no dice cuándo caduca.** Un certificado de hace 5 años sigue
  valiendo.
