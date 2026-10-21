import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

/**
 * Reads a CSV of employees (employeeId,employeeName per line), checks each ID
 * against the cir_emp table, and writes matching IDs to the output file.
 *
 * Usage: java EmployeeLookup <inputFile> <outputFile>
 * Env:   DB_URL, DB_USER, DB_PASSWORD
 */
public class EmployeeLookup {

    private static final String LOOKUP_SQL = "SELECT emp_id FROM cir_emp WHERE emp_id = ?";

    public static void main(String[] args) {
        if (args.length != 2) {
            System.err.println("Usage: java EmployeeLookup <inputFile> <outputFile>");
            System.exit(1);
        }

        String inputFile = args[0];
        String outputFile = args[1];

        String dbUrl = System.getenv("DB_URL");
        String dbUser = System.getenv("DB_USER");
        String dbPassword = System.getenv("DB_PASSWORD");

        if (dbUrl == null || dbUser == null || dbPassword == null) {
            System.err.println("Error: DB_URL, DB_USER and DB_PASSWORD environment variables must be set.");
            System.exit(1);
        }

        int processed = 0;
        int matched = 0;

        try (BufferedReader reader = Files.newBufferedReader(Paths.get(inputFile), StandardCharsets.UTF_8);
             BufferedWriter writer = Files.newBufferedWriter(Paths.get(outputFile), StandardCharsets.UTF_8);
             Connection conn = DriverManager.getConnection(dbUrl, dbUser, dbPassword);
             PreparedStatement stmt = conn.prepareStatement(LOOKUP_SQL)) {

            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty()) {
                    continue;
                }

                String[] parts = line.split(",", 2);
                String employeeId = parts[0].trim();
                if (employeeId.isEmpty()) {
                    continue;
                }

                processed++;
                if (employeeExists(stmt, employeeId)) {
                    writer.write(employeeId);
                    writer.newLine();
                    matched++;
                }
            }
        } catch (IOException e) {
            System.err.println("File error: " + e.getMessage());
            System.exit(2);
        } catch (SQLException e) {
            System.err.println("Database error: " + e.getMessage());
            System.exit(3);
        }

        System.out.println("Processed " + processed + " employee(s); " + matched + " found in cir_emp.");
        System.out.println("Matching IDs written to " + outputFile);
    }

    private static boolean employeeExists(PreparedStatement stmt, String employeeId) throws SQLException {
        stmt.setString(1, employeeId);
        try (ResultSet rs = stmt.executeQuery()) {
            return rs.next();
        }
    }
}
