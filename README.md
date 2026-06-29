# SortIQ
# ♻️ SORTiQ: AI-based Value Component Recovery

SORTiQ is intended to create an intelligent pre-sorting system designed to close the value-recovery gap in e-waste recycling. By moving from destructive bulk shredding to a targeted, component-level depopulation strategy, SORTiQ can improve purity and recovery of Critical Raw Materials (CRMs) while ensuring compliance with modern regulatory mandates.

## 🚀 Project Overview
* **Aim:** Automated detection and recovery of high-value components (PCBs, magnets, RAM) from e-waste streams for targeted recycling or direct reuse.
* **Research Focus:** Investigating the systems-thinking approach to e-waste recovery, specifically managing data uncertainty propagation, industrial safety requirements, and economic trade-offs in automated sorting pipelines.

## 🏗️ Technical Architecture
SORTiQ utilizes a hierarchical, multi-model AI architecture designed to balance industrial throughput with high-precision component identification.

### The Two-Model created by improvising one to another
* **Model 1: YOLOv8 (Detection & Flow Control):**
    * **Role:** Primary object detection and tracking layer.
    * **Function:** Processes the real-time conveyor stream to localize objects, classify general component types, and manage object flow.
    * **Objective:** Optimized for high-throughput inference to ensure no component passes undetected at industrial speeds.
* **Model 2: RT-DETRv2 (Precision Depopulation):**
    * **Role:** High-fidelity identification of CRM-rich components (e.g., ICs, specific chipsets, connectors).
    * **Setup:** Deployed via **ONNX Runtime** to minimize inference latency. 
    * **Function:** Performs precision identification and structural analysis of high-value components, integrated with an OCR pipeline for automated chip marking verification.

### Tracking & Sensor Fusion
* **Tracking Algorithm:** Maintains component identity across the belt using a **Kalman Filter** paired with the **Hungarian Algorithm** for robust object association.
* **Sensing Layer:** Integrated magnetometer arrays for flux density measurement and inductive proximity sensors for high-fidelity component validation.
* **Observability:** Full-stack monitoring via **Grafana and InfluxDB**, with the environment containerized using **Docker** for reproducible deployment.

## 🔧 Engineering Post-Mortem: Real-World Lessons
The transition from PoC to an industrial-ready system required overcoming significant hardware-software integration hurdles:
* **EMI & Brownouts:** High-current actuators caused electrical noise, resulting in serial communication drops. This was mitigated by implementing a "Lazy Servo" PWM protocol to isolate signal pins during idle states.
* **Communication Resilience:** Persistent I2C handshake errors during magnetometer polling were resolved by implementing robust, auto-resetting communication wrappers.
* **Signal Fragmentation:** Asynchronous serial data streams were unified through a full-buffer-drain ingestion algorithm to ensure zero-loss synchronization between the IO layer and the vision brain.

## 🔬 Research Areas & Future Directions
SORTiQ is currently evolving into a testbed for precision depopulation research:
* **Uncertainty Propagation:** Modeling how detection confidence drops—due to occlusion or perspective changes—impacts final sorting accuracy.
* **Traceability:** Development of a framework for Digital Product Passports using QR/OCR to ensure end-to-end component visibility.
* **Economic/Regulatory Alignment:** Analyzing the necessity of AI and automation by mapping the trade-offs between CapEx, OpEx, and the potential revenue uplift from high-purity CRM recovery. This research treats the recycling plant as an integrated system, where intelligent automation is the required catalyst to convert "trash into cash" while meeting stringent regulatory sustainability mandates, such as the EU Critical Raw Materials Act.
