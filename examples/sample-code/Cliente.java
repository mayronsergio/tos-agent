package br.com.acme.cadastro;

import javax.persistence.Entity;
import javax.persistence.Table;
import javax.validation.constraints.NotBlank;

@Entity
@Table(name = "TB_CLIENTE")
public class Cliente {
    @NotBlank(message = "Nome do cliente obrigatorio")
    private String nome;

    private String documento;
}

