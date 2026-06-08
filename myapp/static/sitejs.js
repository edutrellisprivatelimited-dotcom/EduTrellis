/* ============================================================
   CUSTOM CURSOR — desktop (pointer:fine) only
   ============================================================ */
(function(){
  if(!window.matchMedia('(pointer:fine)').matches){
    document.getElementById('cursor').style.display='none';
    document.getElementById('cursorRing').style.display='none';
    return;
  }
  const cur=document.getElementById('cursor');
  const ring=document.getElementById('cursorRing');
  let mx=0,my=0,rx=0,ry=0;
  document.addEventListener('mousemove',function(e){mx=e.clientX;my=e.clientY;cur.style.left=mx+'px';cur.style.top=my+'px';});
  (function animRing(){rx+=(mx-rx)*.14;ry+=(my-ry)*.14;ring.style.left=rx+'px';ring.style.top=ry+'px';requestAnimationFrame(animRing);})();
  document.querySelectorAll('a,button,.prod-card,.why-card,.svc-item,.faq-q').forEach(function(el){
    el.addEventListener('mouseenter',function(){ring.style.width='58px';ring.style.height='58px';ring.style.borderColor='rgba(232,0,30,.7)';});
    el.addEventListener('mouseleave',function(){ring.style.width='38px';ring.style.height='38px';ring.style.borderColor='rgba(232,0,30,.45)';});
  });
})();

/* ============================================================
   LOADER
   ============================================================ */
(function(){
  var pctEl=document.getElementById('loaderPct');
  var p=0;
  var pTimer=setInterval(function(){p=Math.min(p+Math.random()*12,99);pctEl.textContent=Math.floor(p)+'%';},80);
  window.addEventListener('load',function(){
    clearInterval(pTimer);pctEl.textContent='100%';
    setTimeout(function(){document.getElementById('loader').classList.add('hidden');},1500);
  });
})();

/* ============================================================
   MOBILE MENU
   ============================================================ */
var ham=document.getElementById('ham');
var mobileMenu=document.getElementById('mobileMenu');

function closeMobileMenu(){
  mobileMenu.classList.remove('open');
  ham.classList.remove('open');
  ham.setAttribute('aria-expanded','false');
  document.body.style.overflow='';
}

ham.addEventListener('click',function(e){
  e.stopPropagation();
  var isOpen=mobileMenu.classList.toggle('open');
  ham.classList.toggle('open',isOpen);
  ham.setAttribute('aria-expanded',String(isOpen));
  document.body.style.overflow=isOpen?'hidden':'';
});

mobileMenu.querySelectorAll('a').forEach(function(a){
  a.addEventListener('click',closeMobileMenu);
});

document.addEventListener('click',function(e){
  if(mobileMenu.classList.contains('open')&&!mobileMenu.contains(e.target)&&!ham.contains(e.target)){
    closeMobileMenu();
  }
});

document.addEventListener('keydown',function(e){
  if(e.key==='Escape')closeMobileMenu();
});

/* ============================================================
   SMOOTH SCROLL
   ============================================================ */
document.querySelectorAll('a[href^="#"]').forEach(function(a){
  a.addEventListener('click',function(e){
    var href=a.getAttribute('href');
    if(href==='#')return;
    var t=document.querySelector(href);
    if(t){e.preventDefault();t.scrollIntoView({behavior:'smooth',block:'start'});}
  });
});

/* ============================================================
   CONTACT FORM
   ============================================================ */
function clearFieldErrors(form){
  form.querySelectorAll('.field-error').forEach(function(el){
    el.textContent='';
    el.style.display='none';
  });
  form.querySelectorAll('input, textarea, select').forEach(function(el){
    el.style.borderColor='';
  });
}

function setFieldError(form, fieldName, message){
  var errorEl=form.querySelector('[data-error-for="'+fieldName+'"]');
  var inputEl=form.querySelector('[name="'+fieldName+'"]');
  if(errorEl){
    errorEl.textContent=message;
    errorEl.style.display='block';
  }
  if(inputEl){
    inputEl.style.borderColor='#e8001e';
  }
}

function showFormMessage(message, type){
  var box=document.getElementById('formMessage');
  if(!box)return;
  box.textContent=message;
  box.style.display='block';
  if(type==='success'){
    box.style.background='#e8fff1';
    box.style.color='#127a3f';
    box.style.border='1px solid #8ee0af';
  }else{
    box.style.background='#fff1f3';
    box.style.color='#b00015';
    box.style.border='1px solid #f3a7b1';
  }
}

function hideFormMessage(){
  var box=document.getElementById('formMessage');
  if(!box)return;
  box.style.display='none';
  box.textContent='';
}

function validateContactForm(form){
  clearFieldErrors(form);
  hideFormMessage();

  var name=(form.name.value || '').trim();
  var phone=(form.phone.value || '').trim();
  var email=(form.email.value || '').trim();
  var isValid=true;

  if(!name){
    setFieldError(form,'name','Full name is required.');
    isValid=false;
  }else if(name.length < 2){
    setFieldError(form,'name','Full name must be at least 2 characters long.');
    isValid=false;
  }

  var digits=phone.replace(/\D/g,'');
  if(!phone){
    setFieldError(form,'phone','Phone number is required.');
    isValid=false;
  }else if(digits.length < 10){
    setFieldError(form,'phone','Enter a valid phone number.');
    isValid=false;
  }

  if(!email){
    setFieldError(form,'email','Email address is required.');
    isValid=false;
  }else if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)){
    setFieldError(form,'email','Enter a valid email address.');
    isValid=false;
  }

  if(!isValid){
    showFormMessage('Please fix the highlighted fields and try again.','error');
  }

  return isValid;
}

function handleSubmit(e) {
  e.preventDefault();
  var form = e.target;
  var btn = document.getElementById('submitBtn');
  var defaultBtnHtml = '<i class="fas fa-paper-plane"></i> Send Message & Get Callback';

  if(!validateContactForm(form)){
    return;
  }

  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...';
  btn.disabled = true;
  hideFormMessage();

  var data = new FormData(form);

  fetch('/contact/', {
    method: 'POST',
    headers: {
      'X-CSRFToken': data.get('csrfmiddlewaretoken'),
      'X-Requested-With': 'XMLHttpRequest'
    },
    body: data
  })
  .then(function(res) {
    return res.json().then(function(json){
      return { ok: res.ok, status: res.status, json: json };
    });
  })
  .then(function(result) {
    if (result.json.status === 'ok') {
      btn.innerHTML = '<i class="fas fa-check"></i> Message Sent!';
      btn.style.background = 'linear-gradient(135deg,#25d366,#1da851)';
      showFormMessage('Thank you! Your message has been sent successfully.','success');
      form.reset();
      clearFieldErrors(form);
      setTimeout(function() {
        btn.innerHTML = defaultBtnHtml;
        btn.style.background = '';
        btn.disabled = false;
      }, 1200);
      return;
    }

    if (result.json.status === 'validation_error' && result.json.errors) {
      clearFieldErrors(form);
      Object.keys(result.json.errors).forEach(function(field){
        setFieldError(form, field, result.json.errors[field]);
      });
      showFormMessage('Please fix the highlighted fields and try again.','error');
    } else {
      showFormMessage(result.json.detail || 'Something went wrong. Please try again.','error');
    }

    btn.innerHTML = '<i class="fas fa-exclamation-circle"></i> Try Again';
    btn.style.background = 'linear-gradient(135deg,#e8001e,#b00015)';
    btn.disabled = false;
  })
  .catch(function() {
    showFormMessage('Unable to send your message right now. Please try again in a moment.','error');
    btn.innerHTML = '<i class="fas fa-exclamation-circle"></i> Try Again';
    btn.style.background = 'linear-gradient(135deg,#e8001e,#b00015)';
    btn.disabled = false;
  });
}

/* ============================================================
   SCROLL-REVEAL
   ============================================================ */
(function(){
  var ro=new IntersectionObserver(function(entries){
    entries.forEach(function(en){if(en.isIntersecting)en.target.classList.add('vis');});
  },{threshold:0.06,rootMargin:'0px 0px -24px 0px'});
  document.querySelectorAll('.reveal,.reveal-left,.reveal-right,.reveal-scale').forEach(function(el){ro.observe(el);});
})();

/* ============================================================
   HEADER SCROLL SHADOW + SCROLL-TOP BUTTON
   ============================================================ */
window.addEventListener('scroll',function(){
  document.getElementById('mainHeader').classList.toggle('scrolled',window.scrollY>60);
  document.getElementById('scrollTop').classList.toggle('show',window.scrollY>400);
},{passive:true});

/* ============================================================
   ACTIVE NAV LINK
   ============================================================ */
(function(){
  var secs=Array.from(document.querySelectorAll('section[id],div[id="home"]'));
  var deskLinks=document.querySelectorAll('#desktopNav li a');
  var mobLinks=document.querySelectorAll('#mobileMenu li a');
  window.addEventListener('scroll',function(){
    var c='';
    secs.forEach(function(s){if(window.scrollY>=s.offsetTop-160)c=s.id;});
    deskLinks.forEach(function(a){a.classList.toggle('active',a.getAttribute('href')==='#'+c);});
    mobLinks.forEach(function(a){a.classList.toggle('active',a.getAttribute('href')==='#'+c);});
  },{passive:true});
})();

/* ============================================================
   HERO SLIDER
   ============================================================ */
(function(){
  var curSlide=0;
  var total=3;
  var slides=document.querySelectorAll('.slide');
  var dots=document.querySelectorAll('.dot');
  var timer;

  function updateSlider(){
    slides.forEach(function(s,i){s.classList.toggle('active',i===curSlide);});
    dots.forEach(function(d,i){d.classList.toggle('active',i===curSlide);});
  }
  function changeSlide(dir){curSlide=(curSlide+dir+total)%total;updateSlider();resetTimer();}
  function goTo(i){curSlide=i;updateSlider();resetTimer();}
  function resetTimer(){clearInterval(timer);timer=setInterval(function(){changeSlide(1);},6000);}

  window.changeSlide=changeSlide;
  window.goTo=goTo;

  timer=setInterval(function(){changeSlide(1);},6000);

  var touchStartX=0;
  var sliderWrap=document.querySelector('.slider-wrap');
  sliderWrap.addEventListener('touchstart',function(e){touchStartX=e.touches[0].clientX;},{passive:true});
  sliderWrap.addEventListener('touchend',function(e){
    var dx=e.changedTouches[0].clientX-touchStartX;
    if(Math.abs(dx)>45)changeSlide(dx<0?1:-1);
  },{passive:true});
})();

/* ============================================================
   COUNTER ANIMATION
   ============================================================ */
(function(){
  var counterEls=document.querySelectorAll('.counter');
  var cObs=new IntersectionObserver(function(entries){
    entries.forEach(function(en){
      if(en.isIntersecting&&!en.target.dataset.done){
        en.target.dataset.done='1';
        var target=+en.target.dataset.target;
        var dur=1800;
        var steps=60;
        var inc=target/steps;
        var curr=0;
        var t=setInterval(function(){
          curr=Math.min(curr+inc,target);
          en.target.textContent=Math.floor(curr);
          if(curr>=target)clearInterval(t);
        },dur/steps);
      }
    });
  },{threshold:0.5});
  counterEls.forEach(function(el){cObs.observe(el);});
})();

/* ============================================================
   FAQ ACCORDION
   ============================================================ */
function toggleFaq(el){
  var item=el.closest('.faq-item');
  var isOpen=item.classList.contains('open');
  document.querySelectorAll('.faq-item.open').forEach(function(i){i.classList.remove('open');});
  if(!isOpen)item.classList.add('open');
}
window.toggleFaq=toggleFaq;
