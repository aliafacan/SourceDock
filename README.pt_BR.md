<div align="center">

[ **English** ](README.md) &nbsp;•&nbsp; [ **Türkçe** ](README.tr.md) &nbsp;•&nbsp; [ **Deutsch** ](README.de.md) &nbsp;•&nbsp; [ **Español** ](README.es.md) &nbsp;•&nbsp; [ **Português (BR)** ](README.pt_BR.md) &nbsp;•&nbsp; [ **Français** ](README.fr.md)

<br/>

<img src="assets/sourcedock_128.png" width="96" alt="Logotipo do SourceDock" />

# SourceDock

**Aplicativo de desktop e gerenciador de pacotes Linux nativo em GTK 3.**

[![SourceDock CI](https://github.com/aliafacan/SourceDock/actions/workflows/ci.yml/badge.svg)](https://github.com/aliafacan/SourceDock/actions) [![Licença: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

</div>

O SourceDock reúne a busca, instalação, atualização e remoção de aplicativos APT, Flatpak, Snap e pacotes locais em uma interface responsiva. As consultas são assíncronas e os erros de cada provedor são mostrados separadamente.

## Capturas de tela

As imagens abaixo mostram a interface atual da versão 1.4.1 (interface em inglês):

![Aplicativos instalados](docs/screenshots/installed-dark-en-100-1366x768.png)
![Loja e descoberta](docs/screenshots/discover-light-en-100-1366x768.png)
![Central de atualizações](docs/screenshots/updates-dark-en-100-1366x768.png)

## Recursos

- Visões unificadas para aplicativos instalados, pacotes, atualizações e loja.
- Integração com APT e modelos para DNF, Pacman e Zypper; Flatpak e Snap são opcionais.
- Pré-visualização de pacotes `.deb` com versão, arquitetura, dependências e status.
- Temas escuro, claro e do sistema, escala de 90–125 % e seis idiomas.
- Verificação periódica de releases do GitHub e autoatualização por DEB com SHA-256 verificado.
- Operações assíncronas seguras, com bloqueios, limites de tempo e proteção de credenciais.

## Instalação

Baixe o [SourceDock 1.4.1](https://github.com/aliafacan/SourceDock/releases/tag/v1.4.1) e o checksum:

```bash
sha256sum -c sourcedock_1.4.1_all.deb.sha256
sudo apt install ./sourcedock_1.4.1_all.deb
sourcedock
```

Quando uma nova versão está disponível, o SourceDock pode baixar o DEB do GitHub, verificar o checksum e abrir o fluxo normal de pré-visualização e autorização. A instalação sempre exige confirmação do usuário; depois é necessário reiniciar o aplicativo.

## Compatibilidade

- Zorin OS 18.1: instalação real e ciclo APT verificados.
- Ubuntu 22.04 e 24.04: CI PASS, 295/295 testes com Xvfb/Openbox.
- Debian 12: compatível; Debian 11 requer Python 3.10 ou mais recente.
- Fedora, openSUSE e Arch: suporte experimental, sem pacotes nativos por enquanto.

Consulte a [matriz de compatibilidade](docs/COMPATIBILITY.md).

## Desenvolvimento

Requisitos: Python 3.10+, PyGObject, GTK 3, Xvfb, Openbox e `dpkg-dev`.

```bash
python3 main.py
xvfb-run -a bash -c 'openbox >/dev/null 2>&1 & wm=$!; trap "kill $wm 2>/dev/null || true" EXIT; /usr/bin/python3 tools/run_tests.py --require-wm'
bash packaging/build_deb.sh dist
```

Veja o [guia de contribuição](CONTRIBUTING.md), a [arquitetura](docs/ARCHITECTURE.md), a [localização](docs/LOCALIZATION.md), o [changelog](CHANGELOG.md) e a [licença](LICENSE).
