from pathlib import Path

from app.indexing.extractors import extract_symbols


def test_extracts_java_symbols(tmp_path: Path):
    source = tmp_path / "ClienteService.java"
    source.write_text(
        """
        package br.com.acme;
        import javax.persistence.*;
        @Entity
        @Table(name = "TB_CLIENTE")
        public class ClienteService {
            @NotNull
            private String nome;
            public void validarCadastro() {
                throw new IllegalArgumentException("Cliente obrigatorio");
            }
        }
        """,
        encoding="utf-8",
    )

    symbols = extract_symbols(source, tmp_path)
    names = {symbol.name for symbol in symbols}

    assert "ClienteService" in names
    assert "validarCadastro" in names
    assert "TB_CLIENTE" in names
    assert any(symbol.symbol_type == "message" for symbol in symbols)
    assert any(symbol.symbol_type == "validation" for symbol in symbols)

