class AddActiveIncidentUniqueIndex < ActiveRecord::Migration[7.1]
  def up
    # Resolve all but the newest active incident per service so the index can be built.
    execute <<~SQL
      UPDATE incidents
      SET status = 'resolved', resolved_at = NOW(), updated_at = NOW()
      WHERE id IN (
        SELECT id FROM (
          SELECT id, ROW_NUMBER() OVER (PARTITION BY affected_service ORDER BY created_at DESC) AS rn
          FROM incidents
          WHERE status IN ('open', 'investigating') AND affected_service IS NOT NULL
        ) ranked
        WHERE rn > 1
      )
    SQL

    add_index :incidents, :affected_service,
              unique: true,
              where: "status IN ('open', 'investigating')",
              name: 'index_incidents_on_active_affected_service'
  end

  def down
    remove_index :incidents, name: 'index_incidents_on_active_affected_service'
  end
end
