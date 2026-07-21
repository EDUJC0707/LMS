const path=require("path");
const {chromium}=require(path.join(__dirname,"..","test","rpa-test","node_modules","playwright"));
(async()=>{const b=await chromium.launch();const p=await b.newPage();
await p.goto("file://"+path.join(__dirname,"doc.html"),{waitUntil:"networkidle"});await p.waitForTimeout(600);
await p.pdf({path:path.join(__dirname,"LMS 외부서비스 결정.pdf"),format:"A4",printBackground:true,preferCSSPageSize:true});
// QA png
const vp=await b.newPage({viewport:{width:794,height:1123},deviceScaleFactor:2});
await vp.goto("file://"+path.join(__dirname,"doc.html"),{waitUntil:"networkidle"});await vp.waitForTimeout(500);
await vp.evaluate(()=>{document.body.style.background="#fff"});
const h=await vp.evaluate(()=>document.querySelector(".page").scrollHeight);
await vp.setViewportSize({width:794,height:Math.min(h,4000)});
await vp.screenshot({path:path.join(__dirname,"doc-qa.png"),fullPage:true});
await b.close();console.log("pdf+qa done, page height px:",h);})();
