(function(){
  // Before/after slider
  var cmp=document.getElementById('compare'), r=document.getElementById('cmp');
  function setPos(v){cmp.style.setProperty('--pos',v+'%');r.value=Math.round(v);r.setAttribute('aria-valuetext',Math.round(100-v)+' prosenttia jälkeen-kuvaa näkyvissä');}
  var wiping=false, touched=false;
  r.addEventListener('input',function(){touched=true;wiping=false;setPos(+r.value);});
  (function(){
    var reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if(reduce||!('IntersectionObserver' in window)){setPos(50);return;}
    var io=new IntersectionObserver(function(es){es.forEach(function(e){if(!e.isIntersecting||touched)return;io.disconnect();
      var t0=null,D=1800;wiping=true;
      function tick(ts){if(!wiping)return;if(t0===null)t0=ts;var t=Math.min(1,(ts-t0)/D),p=1-Math.pow(1-t,3);setPos(100-100*p);if(t<1)requestAnimationFrame(tick);else wiping=false;}
      setTimeout(function(){requestAnimationFrame(tick);},300);});},{threshold:0.6});
    io.observe(cmp);
  })();

  // Hero: the transformation plays once on load, then the copy drops in
  (function(){
    var reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var cv=document.getElementById('scrubCanvas'); if(reduce||!cv||!cv.getContext)return;
    document.documentElement.classList.add('js-play');
    var mob=window.matchMedia('(max-width:760px)').matches, list=(mob?cv.dataset.m:cv.dataset.f).split(' '), N=list.length;
    var ctx=cv.getContext('2d'), frames=new Array(N), cur=-1, loaded=0, started=false;
    var copy=document.querySelector('.scrub-copy'), shade=document.querySelector('.scrub-shade'), replay=document.getElementById('replay');
    var steps=[].slice.call(document.querySelectorAll('.scrub-steps li'));
    var DUR=3000, TEXT_AT=0.6, START_AFTER=30;
    function src(i){return list[i];}
    for(var j=0;j<N;j++){(function(i){var im=new Image();im.decoding='async';im.onload=function(){im.ok=true;loaded++;if(i===0&&!started)draw(0,true);if(loaded>=START_AFTER)start();};im.onerror=function(){loaded++;if(loaded>=START_AFTER)start();};im.src=src(i);frames[i]=im;})(j);}
    setTimeout(start,900); // don't wait on a slow connection
    function size(){var b=cv.getBoundingClientRect(),d=Math.min(window.devicePixelRatio||1,2);cv.width=Math.round(b.width*d);cv.height=Math.round(b.height*d);var c=cur;cur=-1;draw(c<0?0:c,true);}
    function nearest(i){for(var d=0;d<N;d++){if(frames[i-d]&&frames[i-d].ok)return i-d;if(frames[i+d]&&frames[i+d].ok)return i+d;}return -1;}
    function draw(i,force){var n=nearest(i);if(n<0||(n===cur&&!force))return;cur=n;var im=frames[n],cw=cv.width,ch=cv.height,s=Math.max(cw/im.naturalWidth,ch/im.naturalHeight),w=im.naturalWidth*s,h=im.naturalHeight*s;
      ctx.drawImage(im,(cw-w)*(mob?0.38:0.5),(ch-h)/2,w,h);}
    function ui(p){var label='Ennen';steps.forEach(function(li,idx){var a=parseFloat(li.dataset.at),b=idx+1<steps.length?parseFloat(steps[idx+1].dataset.at):2;var on=p>=a&&p<b;li.classList.toggle('on',on);if(on)label=li.textContent;});}
    function ease(t){return 1-Math.pow(1-t,2.4);} // leaves the old room fast, slows down at the finished one
    function play(){var t0=null,shown=false;replay.classList.remove('on');
      function tick(ts){if(t0===null)t0=ts;var t=Math.min(1,(ts-t0)/DUR),p=ease(t);draw(Math.round(p*(N-1)));ui(p);
        if(!shown&&t>=TEXT_AT){shown=true;copy.classList.add('show');shade.classList.add('show');}
        if(t<1)requestAnimationFrame(tick);else replay.classList.add('on');}
      requestAnimationFrame(tick);}
    function start(){if(started)return;started=true;play();}
    replay.addEventListener('click',play);
    window.addEventListener('resize',size);size();ui(0);
  })();


  // Kotitalousvähennys 2026: 40 %, omavastuu 150 €/hlö, max 2100 €/hlö
  var price=document.getElementById('price'), share=document.getElementById('share'), shareOut=document.getElementById('shareOut');
  var fmt=new Intl.NumberFormat('fi-FI',{maximumFractionDigits:0});
  function calc(){
    var p=Math.max(0,parseFloat(price.value)||0), s=parseInt(share.value,10)/100;
    var ppl=parseInt(document.querySelector('input[name=ppl]:checked').value,10);
    var work=p*s, per=work/ppl, d=0;
    for(var i=0;i<ppl;i++){d+=Math.max(0,Math.min(per*0.40-150,2100));}
    shareOut.textContent=Math.round(s*100)+' %';
    document.getElementById('work').textContent=fmt.format(work)+' €';
    document.getElementById('deduct').textContent=fmt.format(d)+' €';
    document.getElementById('net').textContent=fmt.format(p-d)+' €';
  }
  [price,share].forEach(function(el){el.addEventListener('input',calc)});
  document.querySelectorAll('input[name=ppl]').forEach(function(el){el.addEventListener('change',calc)});
  calc();

  // Form (demo: nothing is sent)
  var form=document.getElementById('quote');
  form.addEventListener('submit',function(e){
    e.preventDefault();
    var ok=true;
    [['f-name','name'],['f-phone','phone']].forEach(function(pair){
      var f=document.getElementById(pair[0]), i=document.getElementById(pair[1]);
      var bad=!i.value.trim(); f.classList.toggle('invalid',bad); if(bad&&ok){i.focus();} ok=ok&&!bad;
    });
    if(ok){form.classList.add('done');form.querySelector('.sent').setAttribute('tabindex','-1');form.querySelector('.sent').focus();}
  });
})();
