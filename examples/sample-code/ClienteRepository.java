package br.com.acme.cadastro;

import java.sql.Connection;
import java.sql.PreparedStatement;

public class ClienteRepository {
    public boolean existeDocumento(Connection connection, String documento) throws Exception {
        PreparedStatement statement = connection.prepareStatement(
            "select id_cliente from TB_CLIENTE where documento = ?"
        );
        statement.setString(1, documento);
        return statement.executeQuery().next();
    }
}

