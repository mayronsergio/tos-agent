package br.com.acme.cadastro;

public class ClienteService {
    private final ClienteRepository repository;

    public ClienteService(ClienteRepository repository) {
        this.repository = repository;
    }

    public void validarCadastro(String nome, String documento) {
        if (nome == null || nome.trim().isEmpty()) {
            throw new IllegalArgumentException("Nome do cliente obrigatorio");
        }
        if (documento == null || documento.length() < 11) {
            throw new IllegalArgumentException("Documento invalido para cadastro de cliente");
        }
    }
}

