import {defineConfig} from '@playwright/test';
const run=process.env.POST_AUDIT_RUN||'complete';
export default defineConfig({testDir:'./tests',testMatch:['e2e/**/*.spec.mjs','post-audit/**/*.spec.mjs'],timeout:90000,fullyParallel:false,workers:1,retries:0,
 reporter:[['line'],['json',{outputFile:`outputs/team-recommender-post-audit/${run}/results.json`}]],outputDir:`outputs/team-recommender-post-audit/${run}/artifacts`,
 use:{extraHTTPHeaders:{'x-post-audit-cohort':'rollout150'},baseURL:'http://127.0.0.1:8771',browserName:'chromium',headless:true,reducedMotion:'reduce',trace:'retain-on-failure',viewport:{width:1280,height:900}},
 webServer:{reuseExistingServer:true,command:'node tools/post_audit_browser_server.mjs',url:'http://127.0.0.1:8771/match_explorer.html',timeout:120000}});
