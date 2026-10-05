//! Portable SQLx migrations without rewriting the database migration ledger.
//!
//! Older Windows checkouts embedded CRLF SQL. Keep that exact representation
//! for already-applied migrations only when its SHA-384 matches. New migrations
//! always use LF, including when building from a CRLF ZIP without Git attributes.

use std::{borrow::Cow, collections::HashMap, error::Error, future::Future, pin::Pin};

use sqlx::{
    migrate::{Migrate, MigrateError, Migration, MigrationSource, Migrator},
    PgPool,
};

static EMBEDDED: Migrator = sqlx::migrate!();

#[derive(Debug)]
struct EmbeddedSource(Vec<Migration>);

type ResolvedMigrations<'a> = Pin<
    Box<dyn Future<Output = Result<Vec<Migration>, Box<dyn Error + Send + Sync>>> + Send + 'a>,
>;

impl<'a> MigrationSource<'a> for EmbeddedSource {
    fn resolve(self) -> ResolvedMigrations<'a> {
        Box::pin(async move { Ok(self.0) })
    }
}

fn with_sql(migration: &Migration, sql: String) -> Migration {
    Migration::new(
        migration.version,
        migration.description.clone(),
        migration.migration_type,
        Cow::Owned(sql),
        migration.no_tx,
    )
}

fn compatible_migration(
    migration: &Migration,
    applied_checksum: Option<&[u8]>,
) -> Result<Migration, MigrateError> {
    let lf = with_sql(migration, migration.sql.replace("\r\n", "\n"));
    let Some(checksum) = applied_checksum else {
        return Ok(lf);
    };
    if lf.checksum.as_ref() == checksum {
        return Ok(lf);
    }
    let crlf = with_sql(migration, lf.sql.replace('\n', "\r\n"));
    if crlf.checksum.as_ref() == checksum {
        tracing::info!(version = migration.version, "using verified CRLF migration history");
        return Ok(crlf);
    }
    // Do not accept arbitrary SQL edits, whitespace edits, or unknown hashes.
    Err(MigrateError::VersionMismatch(migration.version))
}

pub async fn run_migrations(pool: &PgPool) -> Result<(), MigrateError> {
    // Detach so cancellation/errors cannot return a session holding an advisory
    // lock to the pool. Dropping this dedicated connection releases its locks.
    let mut connection = pool.acquire().await?.detach();
    connection.lock().await?;
    let result = async {
        connection.ensure_migrations_table().await?;
        let applied: HashMap<_, _> = connection
            .list_applied_migrations()
            .await?
            .into_iter()
            .map(|migration| (migration.version, migration.checksum))
            .collect();
        let migrations = EMBEDDED
            .iter()
            .map(|migration| {
                compatible_migration(
                    migration,
                    applied.get(&migration.version).map(|checksum| checksum.as_ref()),
                )
            })
            .collect::<Result<Vec<_>, _>>()?;
        let mut migrator = Migrator::new(EmbeddedSource(migrations)).await?;
        // The SAME SQLx lock is already held across history selection and run.
        // SQLx still checks dirty/missing versions and all checksums normally.
        migrator.set_locking(false);
        migrator.run(&mut connection).await
    }
    .await;
    let unlocked = connection.unlock().await;
    result.and(unlocked)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_embedded_migration_accepts_lf_and_crlf_history_from_either_checkout() {
        for migration in EMBEDDED.iter() {
            let lf = with_sql(migration, migration.sql.replace("\r\n", "\n"));
            let crlf = with_sql(migration, lf.sql.replace('\n', "\r\n"));
            for checkout in [&lf, &crlf] {
                for history in [&lf, &crlf] {
                    let selected = compatible_migration(checkout, Some(&history.checksum)).unwrap();
                    assert_eq!(selected.checksum, history.checksum);
                    assert_eq!(selected.sql, history.sql);
                }
                let fresh = compatible_migration(checkout, None).unwrap();
                assert_eq!(fresh.sql, lf.sql);
                assert_eq!(fresh.checksum, lf.checksum);
            }
        }
    }

    #[test]
    fn semantic_edits_and_unknown_history_are_rejected() {
        let original = EMBEDDED.iter().next().unwrap();
        let edited = with_sql(original, format!("{}\nSELECT 1;", original.sql));
        assert!(matches!(
            compatible_migration(&edited, Some(&original.checksum)),
            Err(MigrateError::VersionMismatch(1))
        ));
        assert!(compatible_migration(original, Some(&[0; 48])).is_err());
    }

    #[tokio::test]
    #[ignore = "requires an explicitly supplied disposable PostgreSQL database"]
    async fn postgres_history_and_data_survive_portable_restart() -> anyhow::Result<()> {
        use sqlx::postgres::PgPoolOptions;

        // No fallback to application DATABASE_URL: this gate owns a test DB only.
        let url = std::env::var("P2PKANBAN_MIGRATION_TEST_DATABASE_URL")?;
        let admin = PgPool::connect(&url).await?;
        let schema = format!("portable_{}", uuid::Uuid::now_v7().simple());
        sqlx::query(&format!("CREATE SCHEMA {schema}")).execute(&admin).await?;
        let search_path = format!("SET search_path TO {schema}");
        let pool = PgPoolOptions::new()
            .max_connections(4)
            .after_connect(move |connection, _| {
                let sql = search_path.clone();
                Box::pin(async move {
                    sqlx::query(&sql).execute(connection).await?;
                    Ok(())
                })
            })
            .connect(&url)
            .await?;

        // A real old Windows deployment, with migrations 1 and 2 already run.
        let old = EmbeddedSource(EMBEDDED.iter().take(2).map(|migration| {
            with_sql(migration, migration.sql.replace("\r\n", "\n").replace('\n', "\r\n"))
        }).collect());
        Migrator::new(old).await?.run(&pool).await?;
        sqlx::query("CREATE TABLE portability_marker (value TEXT NOT NULL)").execute(&pool).await?;
        sqlx::query("INSERT INTO portability_marker VALUES ('preserve-me')").execute(&pool).await?;
        let before: Vec<(i64, Vec<u8>)> = sqlx::query_as("SELECT version, checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool).await?;

        // Both concurrent starts use SQLx's lock; one applies the remaining SQL.
        tokio::try_join!(run_migrations(&pool), run_migrations(&pool))?;
        run_migrations(&pool).await?;
        let after: Vec<(i64, Vec<u8>)> = sqlx::query_as("SELECT version, checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool).await?;
        assert_eq!(&after[..before.len()], before.as_slice());
        assert_eq!(after.len(), EMBEDDED.iter().count());
        for (version, checksum) in after.iter().skip(2) {
            let migration = EMBEDDED.iter().find(|m| m.version == *version).unwrap();
            assert_eq!(checksum.as_slice(), compatible_migration(migration, None)?.checksum.as_ref());
        }
        let marker: String = sqlx::query_scalar("SELECT value FROM portability_marker").fetch_one(&pool).await?;
        assert_eq!(marker, "preserve-me");

        // Deliberately corrupt history ONLY in this isolated test schema.
        sqlx::query("UPDATE _sqlx_migrations SET checksum = decode(repeat('00', 48), 'hex') WHERE version = 1")
            .execute(&pool).await?;
        assert!(matches!(run_migrations(&pool).await, Err(MigrateError::VersionMismatch(1))));
        let retained: Vec<u8> = sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations WHERE version = 1")
            .fetch_one(&pool).await?;
        assert_eq!(retained, vec![0; 48]);
        sqlx::query("UPDATE _sqlx_migrations SET checksum = $1 WHERE version = 1")
            .bind(&before[0].1).execute(&pool).await?;
        sqlx::query("UPDATE _sqlx_migrations SET success = false WHERE version = 1").execute(&pool).await?;
        assert!(run_migrations(&pool).await.is_err());
        pool.close().await;
        sqlx::query(&format!("DROP SCHEMA {schema} CASCADE")).execute(&admin).await?;
        admin.close().await;
        Ok(())
    }
}
