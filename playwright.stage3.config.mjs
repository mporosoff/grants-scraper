import {defineConfig} from '@playwright/test';
const run=process.env.STAGE3_BROWSER_RUN||'run2';if(!/^[a-z0-9-]+$/.test(run))throw Error('Invalid local run label');
export default defineConfig({testDir:'./tests/stage3',timeout:90000,workers:1,retries:0,
 reporter:[['line'],['json',{outputFile:`outputs/team-recommender-stage3/browser/${run}/results.json`}]],
 outputDir:`outputs/team-recommender-stage3/browser/${run}/artifacts`,
 use:{baseURL:'http://127.0.0.1:8766',browserName:'chromium',headless:true,reducedMotion:'reduce',trace:'retain-on-failure',viewport:{width:1280,height:900}},
 webServer:{command:'node tests/e2e/static-server.mjs',env:{E2E_PORT:'8766'},url:'http://127.0.0.1:8766/match_explorer.html',timeout:120000}});
