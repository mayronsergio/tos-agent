package br.com.acme.cadastro;

public class ClienteAction {
    private final ClienteService service;

    public ClienteAction(ClienteService service) {
        this.service = service;
    }

    public String salvar() {
        service.validarCadastro("Maria", "12345678901");
        return "clienteSalvo";
    }
}

