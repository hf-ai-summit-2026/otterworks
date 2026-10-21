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
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Reads a CSV of employees (employeeId,employeeName per line), checks each ID
 * against the cir_emp table, and writes matching IDs to the output file in
 * input order. IDs are looked up in batches to avoid one round trip per line.
 *
 * Usage: java EmployeeLookup <inputFile> <outputFile>
 * Env:   DB_URL, DB_USER, DB_PASSWORD
 */
public class EmployeeLookup {

    // Stays under Oracle's 1000-element IN-list limit.
    private static final int BATCH_SIZE = 500;
    private static final int IO_BUFFER_SIZE = 1 << 16;

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

        try (BufferedReader reader = new BufferedReader(
                     Files.newBufferedReader(Paths.get(inputFile), StandardCharsets.UTF_8), IO_BUFFER_SIZE);
             BufferedWriter writer = new BufferedWriter(
                     Files.newBufferedWriter(Paths.get(outputFile), StandardCharsets.UTF_8), IO_BUFFER_SIZE);
             Connection conn = DriverManager.getConnection(dbUrl, dbUser, dbPassword);
             PreparedStatement stmt = conn.prepareStatement(buildLookupSql(BATCH_SIZE))) {

            conn.setReadOnly(true);
            stmt.setFetchSize(BATCH_SIZE);

            List<String> pending = new ArrayList<>(BATCH_SIZE);
            Set<String> distinct = new LinkedHashSet<>(BATCH_SIZE * 2);

            String line;
            while ((line = reader.readLine()) != null) {
                String employeeId = parseEmployeeId(line);
                if (employeeId == null) {
                    continue;
                }

                processed++;
                pending.add(employeeId);
                distinct.add(employeeId);

                if (distinct.size() == BATCH_SIZE) {
                    matched += flush(stmt, writer, pending, distinct);
                }
            }
            if (!pending.isEmpty()) {
                matched += flush(stmt, writer, pending, distinct);
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

    private static String buildLookupSql(int placeholders) {
        StringBuilder sql = new StringBuilder("SELECT emp_id FROM cir_emp WHERE emp_id IN (");
        for (int i = 0; i < placeholders; i++) {
            sql.append(i == 0 ? "?" : ",?");
        }
        return sql.append(')').toString();
    }

    private static String parseEmployeeId(String line) {
        int comma = line.indexOf(',');
        String id = (comma >= 0 ? line.substring(0, comma) : line).trim();
        return id.isEmpty() ? null : id;
    }

    private static int flush(PreparedStatement stmt, BufferedWriter writer,
                             List<String> pending, Set<String> distinct) throws SQLException, IOException {
        Set<String> existing = findExistingIds(stmt, distinct);
        int matched = 0;
        for (String id : pending) {
            if (existing.contains(id)) {
                writer.write(id);
                writer.newLine();
                matched++;
            }
        }
        pending.clear();
        distinct.clear();
        return matched;
    }

    private static Set<String> findExistingIds(PreparedStatement stmt, Set<String> ids) throws SQLException {
        String filler = ids.iterator().next();
        int slot = 1;
        for (String id : ids) {
            stmt.setString(slot++, id);
        }
        // Pad unused slots with a repeat ID so one fixed-size statement serves the final partial batch.
        while (slot <= BATCH_SIZE) {
            stmt.setString(slot++, filler);
        }

        Set<String> existing = new HashSet<>(ids.size() * 2);
        try (ResultSet rs = stmt.executeQuery()) {
            while (rs.next()) {
                String id = rs.getString(1);
                if (id != null) {
                    existing.add(id.trim());
                }
            }
        }
        return existing;
    }
}
