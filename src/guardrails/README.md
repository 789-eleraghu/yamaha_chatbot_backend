# NVIDIA NeMo Guardrails for Yamaha Energy Assistant

## Overview

This module implements guardrails for the Yamaha Industrial Energy Assistant using **NVIDIA NeMo Guardrails** (`nemoguardrails==0.24.1`), Colang rails, and AWS Bedrock (`ChatBedrockConverse`).

Regex matching and crisis hotline responses have been removed. All input validation and output security are performed directly by NVIDIA NeMo Guardrails `LLMRails`.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  USER INPUT                                             │
└─────────────────┬───────────────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────────────┐
│  NVIDIA NeMo INPUT RAILS (src/guardrails/config.yml)    │
│  ├─ NeMo Self-Check Input Rail via AWS Bedrock          │
│  │   ├─ Jailbreak / Instruction Injection prevention   │
│  │   └─ Topic filtering (Yamaha Energy EMS only)        │
│  └─ Fixed Block Responses (Off-Topic or Confidential)   │
└─────────────────┬───────────────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────────────┐
│  Yamaha Energy Assistant Agent (LangGraph + Bedrock)    │
│  └─ Telemetry, Equipment, Zones, Visualizations         │
└─────────────────┬───────────────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────────────┐
│  NVIDIA NeMo OUTPUT RAILS (src/guardrails/config.yml)   │
│  ├─ Prompt leak detection                               │
│  └─ Internal tool name leak prevention                  │
└─────────────────────────────────────────────────────────┘
```

## Directory Structure

```
src/guardrails/
├── __init__.py              # Module exports (guardrails_service, RailType, GuardrailsResult)
├── config.yml               # NVIDIA NeMo Guardrails configuration & prompts
├── guardrails_service.py    # NeMoGuardrailsService runtime wrapper around LLMRails
├── README.md                # This documentation
└── rails/
    └── main.co              # Colang 1.0 definitions (intents & dialog flows)
```

## Key Components

1. **`LLMRails` Integration**:
   Uses `nemoguardrails.LLMRails` initialized with `RailsConfig.from_path("src/guardrails")` and `LangChainLLMAdapter(get_llm())`.

2. **Input Rails (`self check input`)**:
   - Blocks jailbreaks, instruction overrides, and prompt extraction attempts.
   - Restricts conversations strictly to industrial energy management topics. Off-topic queries receive the standard Yamaha Energy Assistant introduction.

3. **Output Rails (`self check output`)**:
   - Ensures internal system prompts, developer messages, and tool function names are never leaked in assistant output.

4. **Async & Sync Execution**:
   - Asynchronous methods (`check_input_async`, `check_output_async`) for FastAPI streaming pipelines.
   - Synchronous wrappers (`check_input`, `check_output`) for synchronous callers and tests.
