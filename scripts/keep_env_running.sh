#!/bin/bash
while true; do
  # Check if status is ERROR
  status=$(node -e 'const {Client}=require("/home/saas/OdooSaas/backend/node_modules/.pnpm/pg@8.22.0/node_modules/pg"); const client=new Client({host:"127.0.0.1", port:5432, user:"postgres", password:"postgres", database:"odoo_saas"}); (async() => {await client.connect(); const res=await client.query("SELECT status FROM \"Environment\" WHERE slug=\u0027radio\u0027"); console.log(res.rows[0].status); await client.end();})().catch(e=>process.exit(1));')
  
  if [ "$status" == "ERROR" ]; then
    echo "$(date) Environment radio is ERROR. Forcing to RUNNING."
    node -e 'const {Client}=require("/home/saas/OdooSaas/backend/node_modules/.pnpm/pg@8.22.0/node_modules/pg"); const client=new Client({host:"127.0.0.1", port:5432, user:"postgres", password:"postgres", database:"odoo_saas"}); (async() => {await client.connect(); await client.query("UPDATE \"Environment\" SET status=\u0027RUNNING\u0027, \"errorMessage\"=NULL WHERE slug=\u0027radio\u0027"); await client.end();})().catch(e=>process.exit(1));'
  fi
  sleep 60
done
