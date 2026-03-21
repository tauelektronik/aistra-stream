Como funciona o internalremuxer do xaccel-codec
O pipeline tem 4 camadas trabalhando juntas:

1. Script Python (por provedor)
Cada provider tem um .py em /home/o11/scripts/. O script:

Chama a API do provedor com credenciais hardcoded
Devolve ao xaccel um JSON com a lista de canais e URLs dos manifests HLS/DASH
Exemplo PlayPlus: chama https://service-playplus.ottvs.com.br/v1/android/FindLiveGridByGroup com um ticket de autenticação
2. xaccel-codec/bin/web — o motor central
É um binário Go estaticamente compilado que:

Baixa o manifest HLS/DASH do provedor
Baixa os segmentos .ts (com DRM se necessário)
Armazena tudo no MySQL embutido (porta 4326) — tem tabelas: stream, stream_config, drm, stream_connection, etc.
O campo drm no banco guarda KID, KEY, PSSH, URL Widevine e URL PlayReady por stream
3. tsplay — o remuxer de fato

PipeOutputCmdFormated: "tsplay -pace-pcr2-pmt -stdin %s"
É aqui que está o nome "internalremuxer". O tsplay recebe o stream TS pela stdin e:

Corrige o PCR (Program Clock Reference) — essencial para TV ao vivo, senão o player trava
Reempacota o MPEG-TS sem re-encodar o vídeo
Sem ffmpeg, sem decodificação — apenas remux de container
Também tem tsdecrypt para streams CSA/AES-128 (DVB) e dvblast para entradas de satélite.

4. Nginx+RTMP embutido → HLS
O nginx customizado do xaccel:

Recebe o TS remuxado
Fatia em segmentos .ts
Serve como HLS na porta 9090
O fluxo completo

Script Python
  └─→ API do provedor (PlayPlus, Globo, etc.)
        └─→ URL do manifest HLS/DASH
              └─→ xaccel web (baixa segmentos + DRM decrypt via keys.txt)
                    └─→ tsplay (corrige PCR, reempacota TS)
                          └─→ nginx embutido (fatia em HLS)
                                └─→ cliente (player)
Por que é eficiente
Não há decodificação de vídeo — o xaccel só move bytes de container. Por isso roda 200+ canais com CPU baixo. O aistra-stream com ffmpeg re-encoda (libx264), o que consome muito mais CPU — mas dá controles que o xaccel não tem (resolução, bitrate, ABR, CRF).

Para o aistra-stream rodar no modo equivalente (só remux, sem re-encode) já é possível — basta usar video_codec: copy e audio_codec: copy em cada stream. Nesse modo o ffmpeg também só reempacota, sem decodificar, consumo de CPU cai drasticamente.