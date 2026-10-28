"""Coletor de métricas do Instagram: @jesse.rodolfo (chave do Jessé), pelo Zernio.
Só leitura, só GET. Por conta: seguidores e ganho em 7 dias, posts, views e engajamento da semana,
e os 3 posts com mais views em 28 dias. Contas descobertas pelo GET accounts da chave.
A lógica comum fica em _metricas_zernio.py."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _base import rodar
from _metricas_zernio import coletar_rede


def coletar():
    return coletar_rede("metricas_instagram", "Métricas do Instagram", "instagram", ("jesse",))


if __name__ == "__main__":
    rodar(coletar)
