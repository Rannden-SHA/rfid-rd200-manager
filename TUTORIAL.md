# RFID Wristband Manager — Tutorial Completo

Aplicacion de escritorio para leer, escribir y configurar pulseras RFID con el lector **RD200-M1-G** (VID: `0x0E6A`, PID: `0x0317`).

---

## Tabla de contenidos

1. [Requisitos previos](#1-requisitos-previos)
2. [Instalacion](#2-instalacion)
3. [Configuracion del driver USB en Windows](#3-configuracion-del-driver-usb-en-windows)
4. [Verificacion del entorno](#4-verificacion-del-entorno)
5. [Uso por linea de comandos (CLI)](#5-uso-por-linea-de-comandos-cli)
6. [Interfaz grafica (GUI)](#6-interfaz-grafica-gui)
   - 6.1 [Pestana Manual](#61-pestana-manual)
   - 6.2 [Pestana Batch / Kiosko](#62-pestana-batch--kiosko)
   - 6.3 [Pestana Sniffer HID](#63-pestana-sniffer-hid)
   - 6.4 [Pestana Config. Lector](#64-pestana-config-lector)
7. [Descubrir el protocolo real del lector](#7-descubrir-el-protocolo-real-del-lector)
8. [Archivo de configuracion (settings.json)](#8-archivo-de-configuracion-settingsjson)
9. [Estructura del proyecto](#9-estructura-del-proyecto)
10. [Solucion de problemas](#10-solucion-de-problemas)

---

## 1. Requisitos previos

| Requisito | Version minima |
|-----------|---------------|
| Python | 3.9 o superior |
| Sistema operativo | Windows 10/11 (tambien compatible con Linux/macOS) |
| Lector RFID | RD200-M1-G conectado por USB |
| Driver USB | WinUSB o libusb (instalado via Zadig en Windows) |

---

## 2. Instalacion

### Paso 1 — Clonar o descargar el proyecto

Copia la carpeta `App-Lectores-Pulseras` en la ubicacion que prefieras.

### Paso 2 — Crear un entorno virtual (recomendado)

```bash
cd App-Lectores-Pulseras
python -m venv venv
```

Activar el entorno:

- **Windows (cmd):**
  ```
  venv\Scripts\activate
  ```
- **Windows (PowerShell):**
  ```
  venv\Scripts\Activate.ps1
  ```
- **Linux/macOS:**
  ```
  source venv/bin/activate
  ```

### Paso 3 — Instalar dependencias

```bash
pip install -r requirements.txt
```

Esto instala:

| Paquete | Funcion |
|---------|---------|
| `customtkinter` | Framework de interfaz grafica moderna |
| `hidapi` | Comunicacion HID directa con el lector |
| `pyusb` | Acceso USB de bajo nivel (fallback) |
| `libusb-package` | Backend libusb para pyusb en Windows |
| `Pillow` | Manejo de imagenes en la GUI |
| `pyserial` | Fallback si el lector expone puerto COM |
| `playsound` | Sonidos de confirmacion en modo batch |

---

## 3. Configuracion del driver USB en Windows

El lector RD200-M1-G se presenta como un dispositivo HID. Para que la app pueda comunicarse directamente con el (en lugar de que Windows lo trate solo como teclado), necesitas instalar un driver alternativo.

### Paso 1 — Descargar Zadig

Descarga Zadig desde https://zadig.akeo.ie/ y ejecutalo como administrador.

### Paso 2 — Seleccionar el dispositivo

1. En el menu de Zadig, ve a **Options > List All Devices**.
2. En el desplegable, busca tu lector. Aparecera con el VID `0E6A` y PID `0317`. Si no ves el nombre exacto, buscalo por esos identificadores.

### Paso 3 — Instalar el driver

1. En el campo "Driver", selecciona **WinUSB** (o **libusb-win32** como alternativa).
2. Haz clic en **Replace Driver** (o **Install Driver** si no tiene uno previo).
3. Espera a que termine. Puede tardar unos segundos.

### Paso 4 — Verificar

Desconecta y reconecta el lector. Luego ejecuta:

```bash
python check_env.py
```

Deberias ver algo como:

```
  OK  Lector encontrado: RD200-M1-G
     Path: \\?\hid#vid_0e6a&pid_0317...
```

> **Nota**: Si necesitas volver a usar el lector como teclado HID (sin esta app), desinstala el driver WinUSB desde el Administrador de dispositivos de Windows y reconecta el lector.

---

## 4. Verificacion del entorno

Antes de lanzar la app por primera vez, ejecuta el script de diagnostico:

```bash
python check_env.py
```

Este script verifica:

- Que todas las librerias Python estan instaladas
- Que el lector RD200-M1-G esta conectado y es detectable via HID
- Que los drivers estan correctamente configurados

**Ejemplo de salida exitosa:**

```
============================================================
  RFID Wristband Manager — Verificacion de Entorno
============================================================
  Python: 3.11.5

  OK  customtkinter          OK
  OK  hidapi                 OK
  OK  pyusb                  OK
  OK  Pillow                 OK
  OK  pyserial               OK

  Buscando lector RD200-M1-G...
  OK  Lector encontrado: RD200-M1-G
     Path: \\?\hid#vid_0e6a&pid_0317...
     Serial: N/A

  Entorno listo. Ejecuta: python app.py
============================================================
```

---

## 5. Uso por linea de comandos (CLI)

La app acepta argumentos por linea de comandos usando `argparse`. Puedes configurar el lector sin abrir la GUI.

### Abrir la GUI (modo normal)

```bash
python app.py
```

### Abrir la GUI con tema claro

```bash
python app.py --theme light
```

### Abrir la GUI con logging de depuracion

```bash
python app.py --debug
```

### Listar todos los dispositivos HID conectados

```bash
python app.py --list-devices
```

Salida de ejemplo:

```
     VID       PID  Fabricante                    Producto
--------------------------------------------------------------------------------
  0x0e6a    0x0317  Generic                       RFID Reader  <<< RD200-M1-G
  0x046d    0xc52b  Logitech                      USB Receiver
```

### Configurar el lector sin abrir la GUI

Desactivar el buzzer y guardar en EEPROM:

```bash
python app.py --config-reader --beep off --save --no-gui
```

Activar emulacion de teclado y cambiar formato de ID:

```bash
python app.py --config-reader --keyboard-emulation on --id-format 10D --save --no-gui
```

Configurar el lector y luego abrir la GUI:

```bash
python app.py --config-reader --beep on --keyboard-emulation off --id-format 10H
```

### Referencia completa de argumentos

| Argumento | Valores | Descripcion |
|-----------|---------|-------------|
| `--theme` | `dark`, `light`, `system` | Tema de la GUI |
| `--debug` | *(flag)* | Activa logging DEBUG en consola |
| `--no-gui` | *(flag)* | No abrir la GUI (usar con --config-reader o --list-devices) |
| `--config-reader` | *(flag)* | Aplicar configuracion al lector |
| `--beep` | `on`, `off` | Activar/desactivar buzzer |
| `--keyboard-emulation` | `on`, `off` | Activar/desactivar emulacion de teclado |
| `--id-format` | `10H`, `10D`, `13D`, `10H-13D`, `RAW` | Formato de salida del UID |
| `--save` | *(flag)* | Guardar config en la EEPROM del lector |
| `--list-devices` | *(flag)* | Listar dispositivos HID y salir |

---

## 6. Interfaz grafica (GUI)

Al ejecutar `python app.py` se abre la ventana principal con cuatro pestanas.

La barra inferior muestra el estado de conexion en tiempo real:

- **Verde**: Lector conectado
- **Naranja**: Buscando lector...
- **Rojo**: Lector desconectado (reconexion automatica cada 3 segundos)

---

### 6.1 Pestana Manual

La pestana por defecto. Permite interactuar con una pulsera individual.

#### Leer el UID de una pulsera

1. Acerca la pulsera al lector.
2. Haz clic en **"Leer UID"**.
3. El panel izquierdo mostrara:
   - **UID** en hexadecimal (ej. `A1B2C3D4`)
   - **UID en decimal** (ej. `2714189780`)
   - **Tipo de tarjeta** (ej. MIFARE Classic 1K)
   - **Timestamp** de la lectura

> Si el polling esta activo (lo esta por defecto al conectar), la tarjeta se detecta automaticamente al acercarla sin necesidad de pulsar el boton.

#### Leer todos los bloques de memoria

1. Acerca la pulsera al lector.
2. Haz clic en **"Leer todos los bloques"**.
3. El panel derecho mostrara los primeros 16 bloques con formato:
   ```
   Bloque 000: A1 B2 C3 D4 E5 F6 07 08 09 0A 0B 0C 0D 0E 0F 10  |  ............
   Bloque 001: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00  |  ................
   ```
4. Puedes cambiar la **clave de autenticacion** y el **tipo de clave** (A o B) antes de leer.

#### Escribir un bloque

1. En el panel derecho, seccion "Escribir bloque":
   - **N. Bloque**: Numero del bloque destino (0-255). Evita los sector trailers (3, 7, 11, 15...).
   - **Datos (hex 16B)**: Los 16 bytes a escribir, separados por espacios.
   - **Clave Auth**: La clave MIFARE de 6 bytes (por defecto `FF FF FF FF FF FF`).
   - **Tipo de clave**: A o B.
2. Haz clic en **"Escribir bloque"** (boton rojo).
3. El resultado aparecera en la barra de estado inferior del panel.

> **Cuidado**: Escribir en sector trailers (bloques 3, 7, 11, 15...) puede bloquear la tarjeta permanentemente si introduces claves incorrectas.

#### Limpiar pantalla

El boton **"Limpiar pantalla"** resetea tanto el panel de tarjeta como el de bloques.

---

### 6.2 Pestana Batch / Kiosko

Modo de cadena de montaje: configura una vez, procesa multiples pulseras sin tocar el raton ni el teclado.

#### Configurar el batch

En el panel izquierdo:

1. **Escribir en bloque** (checkbox): Marca si quieres que cada pulsera reciba datos escritos.
   - **N. Bloque**: Bloque destino.
   - **Datos (hex)**: Los 16 bytes a escribir en cada pulsera.
   - **Clave Auth**: Clave MIFARE.
   - **Tipo de clave**: A o B.
2. **Feedback del lector**:
   - **Beep al exito**: El lector emite un pitido cuando la configuracion se aplica correctamente.
   - **Beep al error**: Pitido diferente cuando hay un error.

#### Iniciar el modo batch

1. Configura los parametros deseados.
2. Haz clic en **"INICIAR"** (boton verde).
3. El panel derecho muestra un estado visual grande:

   | Estado | Color | Significado |
   |--------|-------|-------------|
   | ESPERANDO PULSERA | Oscuro | Listo para la siguiente pulsera |
   | LEYENDO... | Azul | Tarjeta detectada, procesando |
   | CONFIGURACION EXITOSA | Verde | Escritura completada con exito |
   | ERROR EN CONFIGURACION | Rojo | Fallo en la escritura |

4. Acerca una pulsera → se configura automaticamente → retirala → acerca la siguiente.
5. Los contadores **Total / OK / Errores** se actualizan en tiempo real.

#### Historial de sesion

El panel inferior izquierdo muestra un log con cada tarjeta procesada:

```
OK 14:32:05  UID:A1B2C3D4  Configuracion aplicada correctamente.
X  14:32:12  UID:E5F60708  Fallo al escribir bloque 4
```

#### Detener el batch

Haz clic en **"DETENER"** (boton rojo). Puedes resetear los contadores con el boton dedicado.

---

### 6.3 Pestana Sniffer HID

El sniffer integrado reemplaza la necesidad de Wireshark + USBPcap. Permite descubrir el protocolo del lector enviando tramas crudas y viendo las respuestas.

#### Iniciar la captura

1. Asegurate de que el lector esta conectado (barra inferior en verde).
2. Haz clic en **"Iniciar captura"**.
3. El sniffer toma control del dispositivo HID. El polling normal de tarjetas se pausa automaticamente.

> **Importante**: Mientras el sniffer esta activo, las otras pestanas (Manual, Batch) no pueden comunicarse con el lector.

#### Enviar una trama hex

1. En el campo inferior, escribe los bytes en hexadecimal separados por espacios:
   ```
   02 01 25 24 03
   ```
2. Pulsa **Enter** o haz clic en **"Enviar"**.
3. En el log aparecera:
   - **TX** (azul): Lo que enviaste al lector
   - **RX** (verde): La respuesta del lector

Ejemplo de salida:

```
    #    Hora          Dir    Datos Hex                                         ASCII              Notas
------------------------------------------------------------------------------------------------------
    1    14:35:02.123   TX    02 01 25 24 03                                    ..%$.              STX frame | ETX ok | CMD=0x25
    2    14:35:02.131   RX    02 06 00 25 A1 B2 C3 D4 E5 03                    ...%......         STX frame | ETX ok | CMD=0x25 | payload=10B
```

#### Historial de comandos

- Usa las flechas **arriba/abajo** en el campo de texto para navegar por los ultimos 50 comandos enviados.

#### Comandos rapidos

Debajo del campo de envio hay botones predefinidos:

| Boton | Trama hex | Descripcion |
|-------|-----------|-------------|
| Get UID | `02 01 25 24 03` | Solicita el UID de la tarjeta presente |
| Get FW Ver | `02 01 01 00 03` | Solicita la version de firmware |
| Beep ON | `02 02 08 01 0B 03` | Activa el buzzer |
| Beep OFF | `02 02 08 00 0A 03` | Desactiva el buzzer |

> Estos son valores PLACEHOLDER. Personaliza los botones editando la lista `quick_commands` en `gui/sniffer_tab.py` una vez descubras las tramas reales.

#### Ajustar el timeout

Selecciona el timeout de respuesta en el desplegable (200ms a 5000ms). Si el lector tarda en responder, aumenta el valor.

#### Filtrar el trafico

Usa los botones de filtro en la barra superior:

- **ALL**: Muestra TX y RX
- **TX**: Solo paquetes enviados al lector
- **RX**: Solo respuestas del lector

#### Pausa y auto-scroll

- **Pausar**: Congela la vista del log (los paquetes se siguen capturando en el buffer interno).
- **Auto-scroll**: Cuando esta activado, el log se desplaza automaticamente al ultimo paquete.

#### Menu contextual (clic derecho)

Haz clic derecho sobre cualquier linea del log:

- **Copiar linea**: Copia la linea completa al portapapeles.
- **Copiar hex**: Extrae y copia solo los bytes hexadecimales.
- **Reenviar este TX**: Carga el comando TX de esa linea en el campo de envio y lo envia.

#### Exportar capturas

Haz clic en **"Exportar"** en la barra superior:

| Opcion | Resultado |
|--------|-----------|
| **Exportar a CSV** | Guarda un archivo `.csv` con todas las capturas (timestamp, direccion, hex, ASCII, notas) |
| **Copiar como texto** | Copia al portapapeles toda la sesion en texto plano formateado |
| **Generar codigo Python** | Abre una ventana con un snippet listo para pegar en `core/rfid_protocol.py` |

La opcion **"Generar codigo Python"** es la mas importante: convierte automaticamente todos los paquetes TX capturados en constantes `bytes.fromhex()`:

```python
# Paquete TX #1 @ 14:35:02.123
# Nota: STX frame | ETX ok | CMD=0x25
CMD_001 = bytes.fromhex("020125240​3")

# Paquete TX #2 @ 14:35:15.456
CMD_002 = bytes.fromhex("020208010b03")
```

#### Detener la captura

Haz clic en **"Detener captura"**. El polling normal de tarjetas se reactivara cuando cambies a otra pestana y el lector se reconecte.

#### Limpiar

El boton **"Limpiar"** borra el log y el buffer de capturas.

---

### 6.4 Pestana Config. Lector

Permite modificar los parametros internos del hardware del lector RD200-M1-G.

#### Parametros configurables

| Parametro | Opciones | Descripcion |
|-----------|----------|-------------|
| **Buzzer interno** | ON / OFF | Activa o desactiva el pitido al leer tarjeta |
| **Emulacion de teclado HID** | ON / OFF | Cuando esta activa, el lector "escribe" el UID como si fuera un teclado |
| **Formato de salida del UID** | 10H, 10D, 13D, 10H-13D, RAW | Como se formatea el UID en la salida de teclado |

> **Nota**: Desactiva la emulacion de teclado para poder usar la API de comandos directos (modo sniffer y modo manual).

#### Aplicar cambios

- **"Aplicar y Guardar"**: Envia los comandos al lector Y guarda en su EEPROM interna (persisten tras reinicio).
- **"Solo Aplicar"**: Aplica los cambios en la sesion actual, pero se pierden al desconectar el lector.

#### Diagnostico

En el panel derecho:

- **"Escanear dispositivos HID"**: Lista todos los dispositivos HID detectados. El RD200 aparece marcado con una flecha.
- **"Solicitar version de firmware"**: Envia el comando GET_VERSION y muestra la respuesta.
- **"Test LED verde / rojo"**: Enciende brevemente el LED del lector (util para verificar la comunicacion).

#### Envio manual de trama HEX

En la seccion inferior del panel derecho puedes enviar una trama hex cruda:

1. Escribe los bytes (ej. `02 0D 03 08`).
2. Haz clic en **"Enviar trama"**.
3. El campo inferior muestra TX (lo enviado) y RX (la respuesta).

> Este es un mini-sniffer rapido. Para sesiones de exploracion mas completas, usa la pestana **Sniffer HID**.

---

## 7. Descubrir el protocolo real del lector

Los comandos del archivo `core/rfid_protocol.py` tienen valores **PLACEHOLDER**. Para que la app funcione con tu lector RD200-M1-G especifico, necesitas descubrir las tramas reales.

### Metodo 1: Usando el Sniffer integrado (recomendado)

1. Abre la app: `python app.py`
2. Ve a la pestana **Sniffer HID** e inicia la captura.
3. Prueba los comandos rapidos y observa las respuestas.
4. Acerca una pulsera y observa que datos envia el lector espontaneamente.
5. Experimenta variando bytes de los comandos para entender la estructura.
6. Cuando identifiques las tramas correctas, usa **Exportar > Generar codigo Python**.
7. Pega el codigo generado en `core/rfid_protocol.py` reemplazando los PLACEHOLDER.

### Metodo 2: Capturar trafico del software oficial con Wireshark

Si tienes el software oficial del RD200:

1. Instala **Wireshark** con el componente **USBPcap**.
2. Inicia una captura en el bus USB donde esta el lector.
3. Abre el software oficial y ejecuta cada accion (leer tarjeta, cambiar buzzer, etc.).
4. En Wireshark, filtra: `usb.idVendor == 0x0e6a`
5. Busca los paquetes **OUT** (host hacia device) — esos son los comandos.
6. Busca los paquetes **IN** (device hacia host) — esas son las respuestas.
7. Copia los payloads hex y reemplaza los PLACEHOLDER en `core/rfid_protocol.py`.

### Donde reemplazar en el codigo

En `core/rfid_protocol.py`, busca las marcas `PLACEHOLDER` y `TODO`:

```python
# Estructura de trama: [STX][LEN][CMD][DATA...][BCC][ETX]
# Ejemplo real capturado: TX: 02 0D 03 08 ...

CMD_GET_VERSION      = 0x01   # <-- Reemplazar con el byte CMD real
CMD_BUZZER           = 0x08   # <-- Reemplazar
CMD_READ_BLOCK       = 0x20   # <-- Reemplazar
CMD_GET_UID          = 0x25   # <-- Reemplazar
```

Tambien ajusta los metodos de parseo:

- `parse_response()`: Ajustar los offsets segun el formato de respuesta real.
- `parse_uid()`: Ajustar segun donde vienen los bytes del UID en la respuesta.

---

## 8. Archivo de configuracion (settings.json)

El archivo `config/settings.json` controla el comportamiento de toda la aplicacion. Se carga al inicio y se puede editar manualmente.

### Seccion `reader`

```json
"reader": {
    "vid": "0x0E6A",              // Vendor ID del lector
    "pid": "0x0317",              // Product ID del lector
    "poll_interval_ms": 300,      // Intervalo de polling (ms)
    "read_timeout_ms": 500,       // Timeout de lectura HID (ms)
    "auto_reconnect": true,       // Reconectar automaticamente si se desconecta
    "reconnect_interval_s": 3     // Segundos entre intentos de reconexion
}
```

### Seccion `reader_hardware`

```json
"reader_hardware": {
    "buzzer_enabled": true,           // Estado inicial del buzzer
    "keyboard_emulation": false,      // Estado inicial de emulacion de teclado
    "output_format": "10H",           // Formato de salida del UID
    "led_on_read": "green"            // Color del LED al leer tarjeta
}
```

### Seccion `batch`

```json
"batch": {
    "target_block": null,             // Bloque destino (null = solo lectura)
    "block_data_hex": "",             // Datos a escribir en hex
    "auth_key_hex": "FFFFFFFFFFFF",   // Clave MIFARE por defecto
    "auth_key_type": "A",             // Tipo de clave (A o B)
    "beep_on_success": true,          // Beep al exito
    "beep_on_error": true,            // Beep al error
    "led_success": "green",           // Color LED exito
    "led_error": "red",               // Color LED error
    "auto_save_history": true,        // Guardar historial automaticamente
    "history_file": "batch_history.csv"
}
```

### Seccion `gui`

```json
"gui": {
    "theme": "dark",              // "dark", "light" o "system"
    "color_scheme": "blue",       // Esquema de color de CustomTkinter
    "window_width": 1100,         // Ancho inicial de ventana
    "window_height": 700,         // Alto inicial de ventana
    "font_size": 14,
    "show_raw_hex": false         // Mostrar hex crudo en panel de tarjeta
}
```

### Seccion `logging`

```json
"logging": {
    "level": "INFO",                  // "DEBUG", "INFO", "WARNING", "ERROR"
    "log_file": "rfid_manager.log"    // Archivo de log (rotativo, max 5MB x 3)
}
```

---

## 9. Estructura del proyecto

```
App-Lectores-Pulseras/
|
|-- app.py                        Punto de entrada (CLI + GUI)
|-- check_env.py                  Diagnostico del entorno
|-- requirements.txt              Dependencias Python
|-- TUTORIAL.md                   Este archivo
|
|-- config/
|   +-- settings.json             Configuracion persistente
|
|-- core/                         Logica de negocio (sin GUI)
|   |-- __init__.py
|   |-- reader_manager.py         Conexion HID/USB con el lector
|   |-- rfid_protocol.py          Tramas hex del protocolo (PLACEHOLDER)
|   |-- batch_processor.py        Motor del modo batch/kiosko
|   +-- usb_sniffer.py            Motor del sniffer HID
|
|-- gui/                          Interfaz grafica
|   |-- __init__.py
|   |-- main_window.py            Ventana principal, pestanas, reconexion
|   |-- manual_tab.py             Pestana de lectura/escritura manual
|   |-- batch_tab.py              Pestana de modo batch
|   |-- sniffer_tab.py            Pestana del sniffer HID
|   |-- reader_config_tab.py      Pestana de configuracion del lector
|   +-- widgets/
|       |-- __init__.py
|       +-- status_indicator.py   Widgets: barra de estado, panel de tarjeta
|
|-- utils/                        Utilidades
|   |-- __init__.py
|   |-- hex_utils.py              Conversion y validacion de hex
|   +-- logger.py                 Sistema de logging rotativo
|
+-- assets/
    +-- icons/                    Iconos de la app (vacio por ahora)
```

### Principio de diseno: separacion backend / GUI

- **`core/`** no importa nada de `gui/`. Puede usarse sin interfaz grafica (scripts, CLI, tests).
- **`gui/`** importa de `core/` y `utils/`. Toda la comunicacion con hilos usa `root.after()` para thread-safety.
- **`utils/`** no importa de `core/` ni de `gui/`. Son herramientas independientes.

---

## 10. Solucion de problemas

### El lector no se detecta

1. Ejecuta `python app.py --list-devices` y verifica que aparece con VID `0x0e6a` y PID `0x0317`.
2. Si no aparece:
   - Verifica que el cable USB esta bien conectado.
   - Prueba otro puerto USB.
   - Ejecuta `python check_env.py` para un diagnostico completo.
3. Si aparece pero la app no puede abrirlo:
   - En Windows: instala el driver WinUSB con **Zadig** (ver seccion 3).
   - En Linux: puede ser un problema de permisos. Crea una regla udev:
     ```
     echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="0e6a", ATTRS{idProduct}=="0317", MODE="0666"' | sudo tee /etc/udev/rules.d/99-rd200.rules
     sudo udevadm control --reload-rules
     ```

### Error "hidapi no esta instalado"

```bash
pip install hidapi
```

En Linux puede necesitar la libreria del sistema:

```bash
sudo apt install libhidapi-dev    # Debian/Ubuntu
```

### La app se abre pero el lector no responde a los comandos

Los comandos en `core/rfid_protocol.py` son PLACEHOLDER. Necesitas descubrir las tramas reales de tu lector (ver seccion 7).

### Error al escribir: "tarjeta retirada"

Mantener la pulsera inmovil sobre el lector durante toda la escritura. El proceso tarda menos de 1 segundo, pero cualquier movimiento puede interrumpirlo.

### El modo batch no detecta pulseras nuevas

El batch usa deteccion de cambio de UID. Si acercas la misma pulsera dos veces seguidas sin retirarla, el sistema espera a que desaparezca y vuelva a aparecer antes de procesarla.

### La GUI se congela

Verifica el archivo de log `rfid_manager.log` en la raiz del proyecto. Si hay errores repetitivos de timeout, puede que el lector necesite mas tiempo de respuesta. Aumenta `read_timeout_ms` en `config/settings.json`.

### El sniffer no muestra nada al iniciar

- Asegurate de que el lector esta conectado (barra de estado en verde).
- El sniffer detiene el polling normal. Si acercas una pulsera despues de iniciar la captura, deberias ver paquetes RX si el lector esta en modo emulacion de teclado.
- Si el lector solo responde a comandos (no envia datos espontaneamente), usa el campo de envio para mandar tramas y ver las respuestas.

### Quiero volver a usar el lector como teclado

1. Cierra la app.
2. En Windows: abre el Administrador de dispositivos, busca el lector, haz clic derecho > Desinstalar dispositivo (marcando "Eliminar driver").
3. Desconecta y reconecta el lector. Windows reinstalara el driver HID generico.
