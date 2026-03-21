# Vendor Binaries — Linux x86_64

Binários pré-compilados para instalação offline/independente.
O `install.sh` usa estes arquivos primeiro, sem precisar de download externo.

| Arquivo      | Versão         | Fonte                                      |
|--------------|----------------|--------------------------------------------|
| `yt-dlp`     | 2026.03.17     | github.com/yt-dlp/yt-dlp                  |
| `n_m3u8dl`   | v0.5.1-beta    | github.com/nilaoda/N_m3u8DL-RE            |
| `mp4decrypt` | Bento4 1.6.641 | bok.net/Bento4                            |

## Atualizar binários

Para atualizar, baixe novas versões e substitua os arquivos:

```bash
# yt-dlp
curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
     -o vendor/bin/linux-x64/yt-dlp

# n_m3u8dl (pegar URL da última release em github.com/nilaoda/N_m3u8DL-RE)
# mp4decrypt (pegar de bok.net/Bento4/binaries/)
```
