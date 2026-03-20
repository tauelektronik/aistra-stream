# Infraestrutura para 200 Canais — aistra-stream

## Cenário 1 — Copy mode (sem transcodificação)
> HTTP/HLS direto ou CENC com n_m3u8dl — o mais comum

| Recurso | Mínimo     | Recomendado |
|---------|-----------|-------------|
| CPU     | 16 cores  | 32 cores    |
| RAM     | 32 GB     | 64 GB       |
| Rede    | 1 Gbps    | 2.5 Gbps    |
| Disco   | SSD 500 GB | NVMe 1 TB  |

**Cálculo por stream:**
- RAM: ~100–150 MB
- CPU: ~2–4% de 1 core
- Banda: ~5 Mbps médio

**200 streams:**
- RAM total: ~25 GB
- CPU: ~8–10 cores
- Banda de entrada: **1 Gbps**

---

## Cenário 2 — Transcodificação (libx264 / h264_nvenc)
> ffmpeg recodificando vídeo — CPU pesado, GPU recomendada

| Recurso | Necessário              |
|---------|------------------------|
| CPU     | 64+ cores (ou GPU)     |
| RAM     | 64–128 GB              |
| GPU     | 2× RTX 4090            |
| Rede    | 10 Gbps                |
| Disco   | NVMe 2 TB              |

- CPU pura é inviável para 200 streams 1080p
- 1× RTX 4090 aguenta ~100 streams 1080p com `h264_nvenc`
- Para 200 streams transcodificados: **2 GPUs**

---

## Cenário 3 — CENC (Disney+, Star+, etc.)
> n_m3u8dl + ffmpeg — mais pesado que HTTP simples

| Recurso | Recomendado  |
|---------|-------------|
| CPU     | 32 cores    |
| RAM     | 64 GB       |
| Rede    | 2.5–10 Gbps |
| Disco   | NVMe 2 TB   |

**Por stream CENC:** ~200–300 MB RAM (n_m3u8dl + ffmpeg)
**200 streams CENC:** ~50–60 GB RAM

---

## Servidor recomendado (bare-metal)

### Hetzner AX102 (~€200/mês)
- **CPU:** AMD Ryzen 9 — 24 cores / 48 threads
- **RAM:** 128 GB DDR4
- **Disco:** 2× NVMe 1.92 TB
- **Rede:** 10 Gbps uplink
- Ideal para copy mode + CENC

### Hetzner EX130 (~€350/mês) — com GPU
- **CPU:** Intel i9-13900 — 24 cores
- **RAM:** 128 GB
- **GPU:** adicionar via dedicated GPU add-on
- Para transcodificação em escala

> **Servidor atual (5.8 GB RAM):** aguenta ~30–40 canais copy mode

---

## Gargalo principal: banda de rede

```
200 canais × 5 Mbps (média) = 1 Gbps só de ENTRADA
+ viewers assistindo        = banda de SAÍDA adicional
```

Para escalar com audiência, link dedicado de **10 Gbps** é necessário.

---

## Ajustes no aistra-stream para escalar

| Parâmetro | Valor atual | Valor para 200ch |
|-----------|------------|-----------------|
| `hls_list_size` | 15 | 5–8 |
| `hls_time` | 15s | 20–30s |
| `buffer_seconds` | 20 | 30 |

**Outras otimizações:**
1. MariaDB em servidor separado (evita contenção de I/O)
2. `/tmp` em `tmpfs` ou RAM disk para segmentos HLS
3. Nginx como proxy reverso para distribuição dos segmentos
4. Limitar `MAX_RESTARTS` do watchdog (já = 5 no código)
5. Monitorar uso de FDs: `ulimit -n 65536` no systemd

---

## Resumo rápido

| Tipo de stream | RAM por canal | 200 canais RAM | CPU por canal |
|---------------|--------------|---------------|---------------|
| Copy (HTTP)   | ~100 MB      | ~20 GB        | ~3%           |
| CENC          | ~250 MB      | ~50 GB        | ~5%           |
| Transcode x264| ~400 MB      | ~80 GB        | ~1 core       |
| Transcode GPU | ~200 MB      | ~40 GB        | GPU           |
