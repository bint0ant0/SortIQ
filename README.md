# SortIQ
# ♻️ SortIQ.ai: AI-Powered E-Waste Pre-Sorting System

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![YOLOv8](https://img.shields.io/badge/YOLOv8-Computer_Vision-yellow)
![MicroPython](https://img.shields.io/badge/MicroPython-RP2040-red)
![Hardware](https://img.shields.io/badge/Hardware-In--The--Loop-brightgreen)

SortIQ.ai is a hardware-in-the-loop proof of concept designed to intelligently automate the pre-sorting of electronic waste. It uses edge AI (YOLOv8) combined with physical industrial sensors to identify, evaluate, and physically divert valuable Critical Raw Materials (CRMs) and hazardous components on a moving conveyor belt.

## 💡 The Opportunity: Intelligent Pre-Sorting
The e-waste recycling industry currently relies heavily on bulk shredding, a highly efficient method for processing large volumes of end-of-life electronics. However, bulk shredding drops CRM purity. SortIQ.ai introduces an automated "pre-sorting" layer to the ecosystem. By utilizing sensor fusion to detect and physically divert CRM-rich components (such as Gold-bearing PCBs and Neodymium permanent magnets) *before* they enter the bulk shredder, facilities can maximize purity and recovery rates. 

Furthermore, SortIQ acts as a safety gate, instantly blocking the belt if Li-Ion batteries or power banks are detected to prevent facility fires.

## 🏗️ System Architecture
SortIQ utilizes a distributed hardware architecture to isolate high-power motor noise from sensitive logic controllers:

1. **The Brain (Edge PC):** Runs the YOLOv8 vision pipeline, aggregates sensor data, and dispatches actuation commands based on a complex decision matrix.
2. **The IO Controller (Raspberry Pi Pico):** Runs MicroPython to poll an MLX90393 Magnetometer, IR object triggers, and Inductive sensors. Controls the Diverter Servo.
3. **The Conveyor Drive (Arduino Nano):** Operates the NEMA/stepper motor on an isolated power and logic circuit to prevent ground loops.

## 📂 Documentation & Media
* [📽️ Watch the SortIQ MVP Demo Video](./media/sortiq_demo.mp4) *(Update link when uploaded)*
* [📊 Read the SortIQ Pitch Deck](./media/pitch_deck.pdf) *(Update link when uploaded)*
* [⚙️ System Architecture & Sensor Fusion](./docs/architecture.md)
* [🔧 Engineering Post-Mortem: Solving EMI & Brownouts](./docs/engineering_post_mortem.md)

## 👥 The Team
SortIQ.ai is built by a multidisciplinary engineering team combining software, systems design, and mechanical expertise:
* **Binto Anto:** Founder | Computer Vision, Machine Learning, and Systems Engineering
* **Amalkrishna Manikkath Jayan:** Process Simulation and Optimization Lead
* **Risal Kolarikandy:** Senior Mechanical Design Engineer | R&D Design and Manufacturing
