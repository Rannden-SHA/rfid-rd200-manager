# rfid-rd200-manager

Aplicación completa en Python para la gestión, diagnóstico y configuración avanzada de lectores RFID **RD200-M1-G**.

Incluye interfaz gráfica moderna (GUI) y modo línea de comandos (CLI), permitiendo tanto uso interactivo como automatización en scripts o despliegues masivos.

---

## ✨ Características

- 🖥️ Interfaz gráfica basada en CustomTkinter
- ⚡ Configuración rápida por CLI
- 🔍 Detección de dispositivos HID conectados
- 🔊 Activación/desactivación del buzzer
- ⌨️ Control de emulación de teclado HID
- 🆔 Configuración de formato de UID:
  - `10H`
  - `10D`
  - `13D`
  - `10H-13D`
  - `RAW`
- 💾 Guardado persistente en EEPROM
- 🐞 Logging y modo debug
- 🧪 Herramientas de diagnóstico integradas

---

## 📦 Requisitos

- Python 3.9+
- pip

Instalar dependencias:

```bash
pip install hidapi customtkinter
```

---

## 🚀 Uso

### 🖥️ Modo GUI

```bash
python app.py
```

Opcional:

```bash
python app.py --theme light
python app.py --debug
```

---

### ⚡ Modo CLI

Configurar el lector sin abrir la interfaz gráfica:

```bash
python app.py --config-reader --beep off
```

Ejemplo completo:

```bash
python app.py \
  --config-reader \
  --keyboard-emulation on \
  --id-format 10D \
  --beep on \
  --save \
  --no-gui
```

---

### 🔍 Diagnóstico

Listar dispositivos HID conectados:

```bash
python app.py --list-devices
```

Modo debug:

```bash
python app.py --debug
```

---

## ⚙️ Parámetros CLI

| Parámetro | Descripción |
|----------|-------------|
| `--config-reader` | Aplica configuración al lector |
| `--beep on/off` | Activa o desactiva el buzzer |
| `--keyboard-emulation on/off` | Activa emulación de teclado |
| `--id-format FORMAT` | Define formato de UID |
| `--save` | Guarda en EEPROM |
| `--no-gui` | No abre la interfaz gráfica |
| `--list-devices` | Lista dispositivos HID |
| `--debug` | Activa logging detallado |
| `--theme` | Tema GUI (`dark`, `light`, `system`) |

---

## 🧠 Ejemplos

### Desactivar buzzer

```bash
python app.py --config-reader --beep off
```

### Activar modo teclado con formato decimal

```bash
python app.py --config-reader --keyboard-emulation on --id-format 10D
```

### Configuración completa persistente

```bash
python app.py --config-reader --beep on --keyboard-emulation off --id-format RAW --save
```

---

## 🔌 Solución de problemas

### No se detecta el lector

1. Verifica conexión USB  
2. Ejecuta:

```bash
python app.py --list-devices
```

3. En Windows:
   - Usa Zadig
   - Instala driver WinUSB / LibUSB

---

## 🏗️ Estructura del proyecto

```
.
├── app.py
├── core/
│   └── reader_manager.py
├── gui/
│   └── main_window.py
├── utils/
│   └── logger.py
└── rfid_protocol.py
```

---

## 🎯 Casos de uso

- Configuración masiva de lectores RFID
- Eventos (pulseras RFID / cashless)
- Control de accesos
- Herramientas internas de soporte técnico
- Automatización de despliegues

---

## 🛠️ Desarrollo

Ejecutar en modo debug:

```bash
python app.py --debug
```

---

## 📄 Licencia

MIT License

---

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Abre un issue o pull request para mejoras, bugs o nuevas funcionalidades.

---

## ⚠️ Nota

Este proyecto está diseñado específicamente para el lector **RD200-M1-G**. Otros dispositivos HID pueden no ser compatibles.
